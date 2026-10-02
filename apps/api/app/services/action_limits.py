"""Short mutation limits measured from committed, self-attributed audit events."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, utcnow


def enforce_action_limit(db: Session, actor_id: str, action: str, *, limit: int = 20) -> None:
    """Caller must lock the actor row before this read, with no pending changes.

    The successful mutation and its audit event commit in the same transaction.
    Holding the actor lock until that commit prevents parallel requests from
    spending the same remaining capacity on SQLite and PostgreSQL.
    """
    if not 1 <= limit <= 20:
        raise ValueError("The mutation limit must be between 1 and 20")
    events = db.scalars(select(AuditEvent.id).where(
        AuditEvent.actor_id == actor_id, AuditEvent.action == action,
        AuditEvent.created_at >= utcnow() - timedelta(minutes=1)).limit(limit)).all()
    if len(events) >= limit:
        raise HTTPException(429, "Отправлено слишком много сообщений. Подождите минуту",
            headers={"Retry-After": "60"})
