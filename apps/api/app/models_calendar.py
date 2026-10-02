"""Persisted weekly availability and durable, deduplicated reminder records."""
from datetime import date, datetime, time

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UTCDateTime, timestamp, uuid_column


class AvailabilityRule(Base):
    __tablename__ = "availability_rules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_availability_weekday"),
        CheckConstraint("end_time > start_time", name="ck_availability_interval"),
        CheckConstraint("slot_minutes BETWEEN 15 AND 120", name="ck_availability_duration"),
        CheckConstraint("horizon_weeks BETWEEN 1 AND 12", name="ck_availability_horizon"),
        CheckConstraint("dst_fold IN ('first','second')", name="ck_availability_fold"),
        CheckConstraint("revision >= 1", name="ck_availability_revision"),
    )
    id: Mapped[str] = uuid_column()
    mentor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time())
    end_time: Mapped[time] = mapped_column(Time())
    timezone: Mapped[str] = mapped_column(String(80))
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30)
    starts_on: Mapped[date] = mapped_column(Date())
    ends_on: Mapped[date | None] = mapped_column(Date())
    horizon_weeks: Mapped[int] = mapped_column(Integer, default=8)
    dst_fold: Mapped[str] = mapped_column(String(10), default="first")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    generated_until: Mapped[date | None] = mapped_column(Date())
    created_at: Mapped[datetime] = timestamp()
    updated_at: Mapped[datetime] = timestamp()


class GeneratedRuleSlot(Base):
    __tablename__ = "generated_rule_slots"
    __table_args__ = (UniqueConstraint("rule_id", "occurrence_key", name="uq_rule_occurrence"),)
    id: Mapped[str] = uuid_column()
    rule_id: Mapped[str] = mapped_column(ForeignKey("availability_rules.id"), index=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey("slots.id"), unique=True)
    occurrence_key: Mapped[str] = mapped_column(String(100))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = timestamp()


class BookingReminder(Base):
    __tablename__ = "booking_reminders"
    __table_args__ = (
        UniqueConstraint("booking_id", "user_id", "kind", name="uq_booking_user_reminder"),
        CheckConstraint("kind IN ('24h','1h')", name="ck_reminder_kind"),
        CheckConstraint("delivery_status IN ('email_queued','in_app_only')", name="ck_reminder_delivery"),
    )
    id: Mapped[str] = uuid_column()
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)
    notification_id: Mapped[str | None] = mapped_column(ForeignKey("notifications.id"))
    email_outbox_id: Mapped[str | None] = mapped_column(ForeignKey("email_outbox.id"))
    delivery_status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = timestamp()
