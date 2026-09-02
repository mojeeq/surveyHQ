"""Sign in, profile and API key management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, client_ip
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.db.base import utcnow
from app.models import ApiKey, User
from app.schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    LoginRequest,
    PasswordChange,
    Token,
    UserOut,
)
from app.schemas.common import Message
from app.services.audit import record

router = APIRouter()


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: DbSession, request: Request) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        # Same message either way so the endpoint cannot enumerate accounts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    user.last_login_at = utcnow()
    record(db, user=user, action="login", ip_address=client_ip(request))
    db.commit()

    token = create_access_token(user.id, {"email": user.email, "role": user.role.value})
    return Token(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


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
