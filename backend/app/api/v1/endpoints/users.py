"""User administration."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, RequireAdmin
from app.core.security import hash_password
from app.models import Role, User
from app.schemas.auth import UserCreate, UserOut, UserUpdate
from app.schemas.common import Message, Page
from app.services.audit import record

router = APIRouter()


@router.get("", response_model=Page[UserOut])
def list_users(
    db: DbSession,
    _: RequireAdmin,
    limit: int = 50,
    offset: int = 0,
    search: str = "",
) -> Page[UserOut]:
    statement = select(User)
    if search:
        pattern = f"%{search.lower()}%"
        statement = statement.where(
            func.lower(User.email).like(pattern) | func.lower(User.full_name).like(pattern)
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    users = db.scalars(
        statement.order_by(User.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page(
        items=[UserOut.model_validate(u) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: DbSession, admin: RequireAdmin) -> User:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    user = User(
        email=email,
        full_name=payload.full_name,
        role=payload.role,
        is_active=payload.is_active,
        restricted_to_projects=payload.restricted_to_projects,
        hashed_password=hash_password(payload.password),
        # An administrator chose this password, so the holder has not yet.
        must_change_password=True,
    )
    db.add(user)
    record(db, user=admin, action="create_user", entity_type="user", detail={"email": email})
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str, payload: UserUpdate, db: DbSession, admin: RequireAdmin
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.role is not None and user.id == admin.id and payload.role != Role.admin:
        raise HTTPException(
            status_code=400, detail="You cannot remove your own administrator role"
        )
    if payload.is_active is False and user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.restricted_to_projects is not None:
        user.restricted_to_projects = payload.restricted_to_projects
    if payload.password:
        user.hashed_password = hash_password(payload.password)
        # A reset by an administrator is someone else's password again.
        user.must_change_password = True

    record(db, user=admin, action="update_user", entity_type="user", entity_id=user_id)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=Message)
def delete_user(user_id: str, db: DbSession, admin: RequireAdmin) -> Message:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    remaining_admins = db.scalar(
        select(func.count()).select_from(User).where(User.role == Role.admin)
    )
    if user.role == Role.admin and (remaining_admins or 0) <= 1:
        raise HTTPException(status_code=400, detail="The last administrator cannot be deleted")

    db.delete(user)
    record(db, user=admin, action="delete_user", entity_type="user", entity_id=user_id)
    db.commit()
    return Message(detail="User deleted")


@router.get("/roles", response_model=list[dict])
def list_roles(_: CurrentUser) -> list[dict]:
    return [
        {"value": Role.viewer.value, "label": "Viewer", "description": "Read dashboards only"},
        {
            "value": Role.analyst.value,
            "label": "Analyst",
            "description": "Build charts, dashboards and run analyses",
        },
        {
            "value": Role.manager.value,
            "label": "Manager",
            "description": "Manage datasets, connections and monitoring rules",
        },
        {
            "value": Role.admin.value,
            "label": "Administrator",
            "description": "Full access including user management",
        },
    ]
