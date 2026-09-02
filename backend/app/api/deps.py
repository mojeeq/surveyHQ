"""FastAPI dependencies: authentication, authorisation and common lookups."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token, hash_api_key
from app.db.base import utcnow
from app.db.session import get_db
from app.models import ApiKey, Dataset, Role, User
from app.services.datasets import dataset_is_queryable

bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> User:
    """Accept either a bearer JWT (browser) or an API key (scripts)."""
    if x_api_key:
        record = db.scalar(
            select(ApiKey).where(
                ApiKey.hashed_key == hash_api_key(x_api_key), ApiKey.revoked.is_(False)
            )
        )
        if record is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        record.last_used_at = utcnow()
        db.commit()
        user = db.get(User, record.user_id)
        if user is None or not user.is_active:
            raise CREDENTIALS_ERROR
        return user

    if credentials is None:
        raise CREDENTIALS_ERROR
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Your session has expired, please sign in again",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.PyJWTError:
        raise CREDENTIALS_ERROR from None

    user_id = payload.get("sub")
    if not user_id:
        raise CREDENTIALS_ERROR
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]


def require_role(minimum: Role):
    """Dependency factory enforcing the role hierarchy."""

    def dependency(user: CurrentUser) -> User:
        if not user.has_role(minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{minimum.value}' role or higher",
            )
        return user

    return dependency


RequireAnalyst = Annotated[User, Depends(require_role(Role.analyst))]
RequireManager = Annotated[User, Depends(require_role(Role.manager))]
RequireAdmin = Annotated[User, Depends(require_role(Role.admin))]


def get_dataset(dataset_id: str, db: DbSession) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


def get_ready_dataset(dataset_id: str, db: DbSession) -> Dataset:
    dataset = get_dataset(dataset_id, db)
    if not dataset_is_queryable(dataset):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Dataset '{dataset.name}' is not ready for querying "
                f"(status: {dataset.status.value})"
            ),
        )
    return dataset


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""
