"""Account privacy requests retain a review trail without promising deletion."""
from datetime import datetime
from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, UTCDateTime, timestamp, uuid_column


class PrivacyRequest(Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('export','deactivate','erase')", name="ck_privacy_kind"),
        CheckConstraint("status IN ('pending','reviewing','fulfilled','rejected')", name="ck_privacy_status"),
    )
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    review_reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = timestamp()
