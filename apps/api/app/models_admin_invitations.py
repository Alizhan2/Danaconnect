"""One-use, email-bound administrator admission with encrypted pending MFA."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UTCDateTime, timestamp, uuid_column


class AdminInvitation(Base):
    __tablename__ = "admin_invitations"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','revoked','expired')", name="ck_admin_invitation_status"),
        CheckConstraint("locale IN ('ru','kk','en')", name="ck_admin_invitation_locale"),
        CheckConstraint("proof_attempts >= 0", name="ck_admin_invitation_attempts"),
        Index("uq_admin_invitation_pending_email", "email", unique=True,
              postgresql_where=text("status = 'pending'"), sqlite_where=text("status = 'pending'")),
        Index("ix_admin_invitation_due", "status", "expires_at"),
    )
    id: Mapped[str] = uuid_column()
    email: Mapped[str] = mapped_column(String(320), index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    locale: Mapped[str] = mapped_column(String(2), default="ru")
    invited_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = timestamp()
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    accepted_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    encrypted_seed: Mapped[str] = mapped_column(Text, default="")
    proof_hash: Mapped[str | None] = mapped_column(String(128), unique=True)
    proof_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    proof_attempts: Mapped[int] = mapped_column(Integer, default=0)


class AdminInvitationChallenge(Base):
    # These OTPs are intentionally separate from ordinary login challenges:
    # /auth/verify-code cannot exchange an invitation OTP for a user/session.
    __tablename__ = "admin_invitation_challenges"
    __table_args__ = (CheckConstraint("attempts >= 0", name="ck_admin_invitation_challenge_attempts"),)
    id: Mapped[str] = uuid_column()
    invitation_id: Mapped[str] = mapped_column(ForeignKey("admin_invitations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = timestamp()
