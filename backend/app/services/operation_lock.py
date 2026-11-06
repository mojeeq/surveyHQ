"""Cross-process locks held until the outer database transaction ends.

All API and worker containers share STORAGE_DIR. File locks are released by
both normal transaction completion and process death; no stale lock TTL.
"""

from __future__ import annotations

import fcntl
import hashlib

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings


class OperationBusy(RuntimeError):
    pass


def acquire(db: Session, key: str) -> None:
    locks = db.info.setdefault("operation_locks", {})
    if key in locks:
        return
    directory = settings.storage_path / "operation-locks"
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / hashlib.sha256(key.encode()).hexdigest()).open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise OperationBusy(
            "Another operation is running in this project. Please retry shortly."
        ) from exc
    db.connection()  # ensure even a read-only operation has a transaction to release
    locks[key] = handle


@event.listens_for(Session, "after_transaction_end")
def release(db: Session, transaction) -> None:
    if transaction.parent is not None:
        return
    for handle in db.info.pop("operation_locks", {}).values():
        handle.close()
