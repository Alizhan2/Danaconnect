"""Serialize persisted mailbox OTP quotas across workers and entrypoints."""
import hashlib

from fastapi import HTTPException
from sqlalchemy import text, update
from sqlalchemy.exc import OperationalError

from app.models import AuthChallenge


def lock_otp_email(db, email):
    # Call before quota reads and hold through OTP enqueue/commit. Invitation
    # callers take this after their inviter/invitation locks: lock_users rolls
    # back first, so taking an advisory lock before it would silently lose it.
    try:
        if db.get_bind().dialect.name == "postgresql":
            key = int.from_bytes(hashlib.sha256(("danaconnect:otp-email:" + email).encode()).digest()[:8], "big", signed=True)
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        elif db.get_bind().dialect.name == "sqlite":
            # A write statement obtains SQLite's writer reservation even when
            # no challenges exist yet. It changes no OTP values or attempts.
            db.execute(update(AuthChallenge).where(AuthChallenge.email == email)
                       .values(attempts=AuthChallenge.attempts))
        else:
            raise HTTPException(503, "Сервис подтверждения email временно недоступен")
    except OperationalError:
        db.rollback()
        raise HTTPException(409, "Подтверждение email обновляется. Повторите попытку") from None
