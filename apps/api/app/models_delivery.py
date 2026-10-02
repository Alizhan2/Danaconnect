"""Durable identity and encrypted delivery records; imported by schema registry."""
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.models import Base, UTCDateTime, timestamp, uuid_column


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        CheckConstraint("status IN ('pending','leased','sent','failed')", name="ck_outbox_status"),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        Index("ix_outbox_due", "status", "next_attempt_at"),
    )
    id: Mapped[str] = uuid_column()
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)
    encrypted_payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = timestamp()
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = timestamp()
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AdminCredential(Base):
    __tablename__ = "admin_credentials"
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    encrypted_totp_secret: Mapped[str] = mapped_column(Text)
    last_used_step: Mapped[int] = mapped_column(Integer, default=-1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = timestamp()


class MFAChallenge(Base):
    __tablename__ = "mfa_challenges"
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = timestamp()


class SessionAssurance(Base):
    __tablename__ = "session_assurances"
    id: Mapped[str] = uuid_column()
    session_id: Mapped[str] = mapped_column(ForeignKey("session_tokens.id", ondelete="CASCADE"), unique=True)
    mfa_verified_at: Mapped[datetime] = timestamp()


class OAuthState(Base):
    __tablename__ = "oauth_states"
    id: Mapped[str] = uuid_column()
    state_hash: Mapped[str] = mapped_column(String(128), unique=True)
    nonce_hash: Mapped[str] = mapped_column(String(128))
    browser_hash: Mapped[str] = mapped_column(String(128))
    encrypted_verifier: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(2), default="ru")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = timestamp()


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_external_identity_subject"),)
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = timestamp()
