"""Sign up, sign in, profile and API key management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, client_ip
from app.core.config import settings
from app.core.rate_limit import enforce
from app.core.security import (
    create_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.db.base import utcnow
from app.models import ApiKey, Role, User
from app.schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    LoginRequest,
    PasswordChange,
    SignupRequest,
    Token,
    UserOut,
)
from app.schemas.common import Message
from app.services.accounts import normalize_username
from app.services.audit import record

router = APIRouter()


# Deliberately per minute rather than per hour: a person who has mistyped their
# password five times pauses for a minute, which is barely an interruption, while
# a machine working through a word list is cut to a rate that will not finish.
LOGIN_ATTEMPTS_PER_IP = 10
LOGIN_ATTEMPTS_PER_ACCOUNT = 5
LOGIN_WINDOW_SECONDS = 60
# Signup is public by design. A modest per-address budget makes automated account
# floods expensive without getting in the way of a real team joining together.
SIGNUPS_PER_IP = 20
SIGNUP_WINDOW_SECONDS = 600


def _token(user: User) -> Token:
    access_token = create_access_token(
        user.id,
        {
            "email": user.email,
            "username": user.username or "",
            "role": user.role.value,
        },
    )
    return Token(
        access_token=access_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/signup", response_model=Token, status_code=201)
def signup(payload: SignupRequest, db: DbSession, request: Request) -> Token:
    """Create a personal SurveyHQ account and sign it in immediately.

    A self-service account is a manager so it can create projects, but it is
    restricted to project memberships. That gives each person their own private
    SurveyHQ workspace by default while still allowing deliberate collaboration.
    """
    address = client_ip(request) or "unknown"
    enforce(
        f"signup:ip:{address}",
        SIGNUPS_PER_IP,
        SIGNUP_WINDOW_SECONDS,
        "Too many accounts have been created from this address. Try again later.",
    )

    email = str(payload.email).lower()
    username = payload.username  # already canonicalised by the schema
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="That username is already taken")

    user = User(
        email=email,
        username=username,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        role=Role.manager,
        is_active=True,
        restricted_to_projects=True,
        must_change_password=False,
        last_login_at=utcnow(),
    )
    db.add(user)
    try:
        # The pre-checks give specific messages in the normal case; the unique
        # indexes are still the authority when two signups race between those
        # checks and this write.
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="That username or email address is already in use",
        ) from exc
    record(
        db,
        user=user,
        action="signup",
        entity_type="user",
        entity_id=user.id,
        ip_address=client_ip(request),
    )
    db.commit()
    return _token(user)


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: DbSession, request: Request) -> Token:
    # Counted before the password is checked, so an attempt costs a caller
    # whether or not it was right - otherwise guessing is free until it works.
    # Both keys are needed: per-address alone lets a botnet spread its guesses
    # at one account, and per-account alone lets one address work through every
    # account it can name.
    identity = payload.identity.lower()
    address = client_ip(request) or "unknown"
    too_many = "Too many sign-in attempts. Wait a minute and try again."
    enforce(f"login:ip:{address}", LOGIN_ATTEMPTS_PER_IP, LOGIN_WINDOW_SECONDS, too_many)
    enforce(
        f"login:account:{identity}",
        LOGIN_ATTEMPTS_PER_ACCOUNT,
        LOGIN_WINDOW_SECONDS,
        too_many,
    )

    if "@" in identity:
        user = db.scalar(select(User).where(User.email == identity))
    else:
        user = db.scalar(select(User).where(User.username == normalize_username(identity)))
    if user is None or not verify_password(payload.password, user.hashed_password):
        # Same message either way so the endpoint cannot enumerate accounts.
        # Keep the historical wording for API clients even though usernames are
        # accepted now too.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    user.last_login_at = utcnow()
    record(db, user=user, action="login", ip_address=client_ip(request))
    db.commit()
    return _token(user)


@router.get("/me", response_model=UserOut)
def read_me(user: CurrentUser) -> User:
    return user


@router.post("/change-password", response_model=Message)
def change_password(payload: PasswordChange, user: CurrentUser, db: DbSession) -> Message:
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    record(db, user=user, action="change_password")
    db.commit()
    return Message(detail="Password updated")


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(user: CurrentUser, db: DbSession) -> list[ApiKey]:
    return list(
        db.scalars(
            select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
        ).all()
    )


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_api_key(payload: ApiKeyCreate, user: CurrentUser, db: DbSession) -> ApiKeyCreated:
    full_key, prefix, hashed = generate_api_key()
    record_row = ApiKey(
        user_id=user.id, name=payload.name or "API key", prefix=prefix, hashed_key=hashed
    )
    db.add(record_row)
    record(db, user=user, action="create_api_key", entity_type="api_key")
    db.commit()
    db.refresh(record_row)
    return ApiKeyCreated(
        id=record_row.id,
        name=record_row.name,
        prefix=record_row.prefix,
        created_at=record_row.created_at,
        last_used_at=None,
        revoked=False,
        key=full_key,
    )


@router.delete("/api-keys/{key_id}", response_model=Message)
def revoke_api_key(key_id: str, user: CurrentUser, db: DbSession) -> Message:
    record_row = db.get(ApiKey, key_id)
    if record_row is None or record_row.user_id != user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    record_row.revoked = True
    record(db, user=user, action="revoke_api_key", entity_type="api_key", entity_id=key_id)
    db.commit()
    return Message(detail="API key revoked")
