"""Learning content, immutable earned events, opt-in ranking, and issued awards."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UTCDateTime, timestamp, uuid_column


class LearningMaterial(Base):
    __tablename__ = "learning_materials"
    __table_args__ = (CheckConstraint("kind IN ('article','video','course','guide')", name="ck_material_kind"),)
    id: Mapped[str] = uuid_column()
    direction_id: Mapped[str | None] = mapped_column(ForeignKey("directions.id"), index=True)
    title_ru: Mapped[str] = mapped_column(String(220))
    title_kk: Mapped[str] = mapped_column(String(220), default="")
    title_en: Mapped[str] = mapped_column(String(220), default="")
    description_ru: Mapped[str] = mapped_column(Text)
    description_kk: Mapped[str] = mapped_column(Text, default="")
    description_en: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(2048))
    content_language: Mapped[str] = mapped_column(String(2), default="ru")
    kind: Mapped[str] = mapped_column(String(20), default="guide")
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = timestamp()
    updated_at: Mapped[datetime] = timestamp()


class PointEvent(Base):
    __tablename__ = "point_events"
    __table_args__ = (
        UniqueConstraint("user_id", "source_type", "source_id", name="uq_point_source"),
        CheckConstraint("points > 0", name="ck_point_amount"),
        CheckConstraint("source_type IN ('completed_meeting','verified_result')", name="ck_point_source"),
    )
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(36))
    points: Mapped[int] = mapped_column(Integer)
    earned_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = timestamp()


class GrowthPrivacy(Base):
    __tablename__ = "growth_privacy"
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    leaderboard_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    alias: Mapped[str] = mapped_column(String(60), default="")
    consent_version: Mapped[str | None] = mapped_column(String(40))
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = timestamp()


class GrowthAward(Base):
    __tablename__ = "growth_awards"
    __table_args__ = (
        CheckConstraint("kind IN ('nomination','certificate')", name="ck_growth_award_kind"),
        CheckConstraint("kind <> 'certificate' OR result_id IS NOT NULL", name="ck_certificate_result"),
        UniqueConstraint("user_id", "result_id", "kind", name="uq_user_result_award"),
    )
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    result_id: Mapped[str | None] = mapped_column(ForeignKey("results.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    title_ru: Mapped[str] = mapped_column(String(220))
    title_kk: Mapped[str] = mapped_column(String(220), default="")
    title_en: Mapped[str] = mapped_column(String(220), default="")
    description_ru: Mapped[str] = mapped_column(Text)
    description_kk: Mapped[str] = mapped_column(Text, default="")
    description_en: Mapped[str] = mapped_column(Text, default="")
    issued_name: Mapped[str] = mapped_column(String(180))
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    issued_at: Mapped[datetime] = timestamp()
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revocation_reason: Mapped[str | None] = mapped_column(Text)
