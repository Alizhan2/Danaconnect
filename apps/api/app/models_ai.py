"""Optional proposals: consent, bounded quota and human decisions are durable."""
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UTCDateTime, timestamp, uuid_column


class AIPreference(Base):
    __tablename__ = "ai_preferences"
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    allow_admin_review: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = timestamp()


class AIUsageCounter(Base):
    __tablename__ = "ai_usage_counters"
    __table_args__ = (UniqueConstraint("day", "scope_key", name="uq_ai_daily_scope"), CheckConstraint("count >= 0", name="ck_ai_count"))
    id: Mapped[str] = uuid_column()
    day: Mapped[date] = mapped_column(Date(), index=True)
    scope_key: Mapped[str] = mapped_column(String(80))
    count: Mapped[int] = mapped_column(Integer, default=0)


class AIProposal(Base):
    __tablename__ = "ai_proposals"
    __table_args__ = (
        CheckConstraint("kind IN ('structure','mentor_recommendation','profile_review')", name="ck_ai_proposal_kind"),
        CheckConstraint("status IN ('pending','ready','failed','approved','dismissed','overridden')", name="ck_ai_proposal_status"),
    )
    id: Mapped[str] = uuid_column()
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    subject_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    input_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    proposal: Mapped[dict | None] = mapped_column(JSON())
    source_facts: Mapped[dict] = mapped_column(JSON(), default=dict)
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(80))
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    review_reason: Mapped[str | None] = mapped_column(Text)
    override_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
