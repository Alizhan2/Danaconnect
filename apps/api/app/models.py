"""Relational schema shared by all platform modules.

IDs are opaque UUID strings. UTCDateTime normalises naive SQLite values back to
aware UTC, so authorization and scheduling comparisons have identical semantics.
"""
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, false, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


def uuid_column():
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


def timestamp():
    return mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class Direction(Base):
    __tablename__ = "directions"
    id: Mapped[str] = uuid_column()
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name_ru: Mapped[str] = mapped_column(String(160))
    name_kk: Mapped[str] = mapped_column(String(160), default="")
    name_en: Mapped[str] = mapped_column(String(160), default="")
    description_ru: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('unchosen','mentee','mentor','admin')", name="ck_user_role"),
        CheckConstraint("account_status IN ('draft','pending','active','changes_requested','suspended')", name="ck_user_status"),
        CheckConstraint("capacity >= 0", name="ck_user_capacity"),
    )
    id: Mapped[str] = uuid_column()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(180), default="")
    role: Mapped[str] = mapped_column(String(20), default="unchosen")
    account_status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    intake_open: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Oral")
    preferred_locale: Mapped[str] = mapped_column(String(2), default="ru", server_default="ru")
    city: Mapped[str] = mapped_column(String(120), default="")
    organization: Mapped[str] = mapped_column(String(300), default="", server_default="")
    phone: Mapped[str | None] = mapped_column(String(40))
    birth_date: Mapped[date | None] = mapped_column(Date)
    bio: Mapped[str] = mapped_column(Text, default="")
    expertise: Mapped[str] = mapped_column(Text, default="")
    evidence_urls: Mapped[list] = mapped_column(JSON, default=list)
    direction_ids: Mapped[list] = mapped_column(JSON, default=list)
    capacity: Mapped[int] = mapped_column(Integer, default=3)
    profile_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    mentor_commitment: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    mentor_commitment_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = timestamp()


class AuthChallenge(Base):
    __tablename__ = "auth_challenges"
    __table_args__ = (CheckConstraint("attempts >= 0", name="ck_challenge_attempts"),)
    id: Mapped[str] = uuid_column()
    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = timestamp()


class SessionToken(Base):
    __tablename__ = "session_tokens"
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    created_at: Mapped[datetime] = timestamp()


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (CheckConstraint("scope IN ('registration','intake','private_project','showcase')", name="ck_document_scope"),)
    id: Mapped[str] = uuid_column()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(250))
    required_roles: Mapped[list] = mapped_column(JSON, default=list)
    direction_id: Mapped[str | None] = mapped_column(ForeignKey("directions.id"), index=True)
    scope: Mapped[str] = mapped_column(String(30), default="registration")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_document_version"),)
    id: Mapped[str] = uuid_column()
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    content_kk: Mapped[str | None] = mapped_column(Text)
    content_en: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = timestamp()


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (UniqueConstraint("user_id", "document_version_id", name="uq_user_version_consent"),)
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    accepted_at: Mapped[datetime] = timestamp()
    method: Mapped[str] = mapped_column(String(50), default="checkbox")
    locale: Mapped[str] = mapped_column(String(2), default="ru", server_default="ru")
    presented_content_hash: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)


class RegistrationReview(Base):
    __tablename__ = "registration_reviews"
    __table_args__ = (CheckConstraint("decision IN ('approved','changes_requested')", name="ck_registration_decision"),)
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    admin_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = timestamp()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("capacity >= 1", name="ck_project_capacity"),
        CheckConstraint("visibility_status IN ('draft','pending','published','hidden')", name="ck_project_visibility"),
    )
    id: Mapped[str] = uuid_column()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mentor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    direction_id: Mapped[str] = mapped_column(ForeignKey("directions.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    problem: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    private_details: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(50), default="idea", index=True)
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    capacity: Mapped[int] = mapped_column(Integer, default=3)
    visibility_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    created_at: Mapped[datetime] = timestamp()


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)
    id: Mapped[str] = uuid_column()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    member_role: Mapped[str] = mapped_column(String(30), default="mentee")
    joined_at: Mapped[datetime] = timestamp()


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','rejected','withdrawn')", name="ck_application_status"),
        CheckConstraint("mentee_id <> mentor_id", name="ck_application_parties"),
        Index("uq_pending_project_application", "project_id", "mentee_id", "mentor_id", unique=True,
              sqlite_where=text("status = 'pending' AND project_id IS NOT NULL"), postgresql_where=text("status = 'pending' AND project_id IS NOT NULL")),
        Index("uq_pending_direct_application", "mentee_id", "mentor_id", unique=True,
              sqlite_where=text("status = 'pending' AND project_id IS NULL"), postgresql_where=text("status = 'pending' AND project_id IS NULL")),
    )
    id: Mapped[str] = uuid_column()
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    mentee_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mentor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    motivation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()


class Participation(Base):
    __tablename__ = "participations"
    __table_args__ = (
        CheckConstraint("status IN ('active','paused','completed_successfully','completed_early')", name="ck_participation_status"),
        CheckConstraint("mentor_id IS NULL OR mentee_id <> mentor_id", name="ck_participation_parties"),
        Index("uq_active_project_participation", "project_id", "mentee_id", unique=True,
              sqlite_where=text("status IN ('active','paused') AND project_id IS NOT NULL"), postgresql_where=text("status IN ('active','paused') AND project_id IS NOT NULL")),
        Index("uq_active_direct_participation", "mentee_id", "mentor_id", unique=True,
              sqlite_where=text("status IN ('active','paused') AND project_id IS NULL"), postgresql_where=text("status IN ('active','paused') AND project_id IS NULL")),
    )
    id: Mapped[str] = uuid_column()
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    mentee_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mentor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    started_at: Mapped[datetime] = timestamp()
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ParticipationEvent(Base):
    __tablename__ = "participation_events"
    id: Mapped[str] = uuid_column()
    participation_id: Mapped[str] = mapped_column(ForeignKey("participations.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = timestamp()


class Slot(Base):
    __tablename__ = "slots"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_slot_interval"),
        CheckConstraint("status IN ('available','booked','cancelled')", name="ck_slot_status"),
        Index("uq_mentor_slot_start", "mentor_id", "starts_at", unique=True,
              sqlite_where=text("status <> 'cancelled'"), postgresql_where=text("status <> 'cancelled'")),
    )
    id: Mapped[str] = uuid_column()
    mentor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Oral")
    status: Mapped[str] = mapped_column(String(30), default="available", index=True)
    created_at: Mapped[datetime] = timestamp()


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled','completed','cancelled','no_show')", name="ck_booking_status"),
        CheckConstraint("mentee_id <> mentor_id", name="ck_booking_parties"),
        Index("uq_scheduled_booking_slot", "slot_id", unique=True,
              sqlite_where=text("status = 'scheduled'"), postgresql_where=text("status = 'scheduled'")),
    )
    id: Mapped[str] = uuid_column()
    slot_id: Mapped[str] = mapped_column(ForeignKey("slots.id"), index=True)
    mentee_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mentor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    participation_id: Mapped[str | None] = mapped_column(ForeignKey("participations.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="scheduled", index=True)
    meeting_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = uuid_column()
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"), unique=True)
    participation_id: Mapped[str | None] = mapped_column(ForeignKey("participations.id"), unique=True)
    created_at: Mapped[datetime] = timestamp()


class ConversationMember(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_conversation_member"),)
    id: Mapped[str] = uuid_column()
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_time", "conversation_id", "created_at"),)
    id: Mapped[str] = uuid_column()
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (
        CheckConstraint("status IN ('completed_successfully','completed_early')", name="ck_result_status"),
        CheckConstraint("verification_status IN ('pending','verified')", name="ck_result_verification"),
        CheckConstraint("meeting_count >= 0", name="ck_result_meeting_count"),
    )
    id: Mapped[str] = uuid_column()
    participation_id: Mapped[str] = mapped_column(ForeignKey("participations.id"), unique=True)
    status: Mapped[str] = mapped_column(String(40))
    exit_reason: Mapped[str] = mapped_column(String(100))
    initiator: Mapped[str] = mapped_column(String(30))
    artifact_url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    meeting_count: Mapped[int] = mapped_column(Integer, default=0)
    verification_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    completed_at: Mapped[datetime] = timestamp()


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("participation_id", "author_id", name="uq_participation_feedback"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_feedback_rating"),
        CheckConstraint("nps IS NULL OR nps BETWEEN 0 AND 10", name="ck_feedback_nps"),
    )
    id: Mapped[str] = uuid_column()
    participation_id: Mapped[str] = mapped_column(ForeignKey("participations.id"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    target_role: Mapped[str] = mapped_column(String(30))
    rating: Mapped[int] = mapped_column(Integer)
    nps: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = timestamp()


class ShowcaseConsent(Base):
    __tablename__ = "showcase_consents"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_showcase_consent"),)
    id: Mapped[str] = uuid_column()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = uuid_column()
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(36))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = timestamp()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(250))
    body: Mapped[str] = mapped_column(Text, default="")
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = timestamp()


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = uuid_column()
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    created_at: Mapped[datetime] = timestamp()
