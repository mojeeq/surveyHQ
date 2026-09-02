"""Append-only audit trail for security-relevant actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import AuditLog, User


def record(
    db: Session,
    *,
    user: User | None,
    action: str,
    entity_type: str = "",
    entity_id: str = "",
    detail: dict[str, Any] | None = None,
    ip_address: str = "",
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else "",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
        ip_address=ip_address,
        created_at=utcnow(),
    )
    db.add(entry)
    return entry
