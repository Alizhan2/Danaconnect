from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UTCDateTime, timestamp, uuid_column


class ProjectComment(Base):
    __tablename__ = "project_comments"
    __table_args__ = (
        CheckConstraint("scope IN ('public','team')", name="ck_comment_scope"),
        CheckConstraint("status IN ('pending','visible','hidden')", name="ck_comment_status"),
        Index("ix_project_comments_time", "project_id", "created_at"),
    )
    id: Mapped[str] = uuid_column()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scope: Mapped[str] = mapped_column(String(10), default="team")
    status: Mapped[str] = mapped_column(String(10), default="visible")
    body: Mapped[str] = mapped_column(Text)
    moderation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()


class TeamInvitation(Base):
    __tablename__ = "team_invitations"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','revoked','expired')", name="ck_invitation_status"),
        Index("uq_pending_project_invitation", "project_id", "target_email", unique=True, sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
    )
    id: Mapped[str] = uuid_column()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    inviter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    target_email: Mapped[str] = mapped_column(String(320), index=True)
    member_role: Mapped[str] = mapped_column(String(30), default="collaborator")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    accepted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = timestamp()
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    email_outbox_id: Mapped[str | None] = mapped_column(ForeignKey("email_outbox.id"))


class PrivateAttachment(Base):
    __tablename__ = "private_attachments"
    __table_args__ = (CheckConstraint("status IN ('active','deleted')", name="ck_attachment_status"), CheckConstraint("size_bytes > 0", name="ck_attachment_size"))
    id: Mapped[str] = uuid_column()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(180))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_provider: Mapped[str] = mapped_column(String(10))
    storage_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = timestamp()
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
