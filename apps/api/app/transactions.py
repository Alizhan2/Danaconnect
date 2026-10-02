"""Portable user-row serialization for changes that affect capacity/access."""
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import User


def lock_users(db: Session, user_ids: list[str]) -> dict[str, User]:
    # Capture IDs before rollback expires ORM state. No pending mutations may
    # precede this helper. SQLite must acquire its writer lock before new reads.
    ids = sorted(set(user_ids))
    db.rollback()
    try:
        if db.get_bind().dialect.name == "sqlite":
            for user_id in ids:
                db.execute(update(User).where(User.id == user_id).values(capacity=User.capacity))
        rows = db.scalars(select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update().execution_options(populate_existing=True)).all()
    except OperationalError:
        db.rollback()
        raise HTTPException(409, "Данные обновляются. Повторите действие")
    output = {user.id: user for user in rows}
    if len(output) != len(ids):
        db.rollback()
        raise HTTPException(404, "Пользователь не найден")
    return output
