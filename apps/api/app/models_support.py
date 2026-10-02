"""Private support correspondence preserves report and moderation history."""
from datetime import datetime
from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, timestamp, uuid_column


class ReportResponse(Base):
    __tablename__ = "report_responses"
    __table_args__ = (Index("ix_report_responses_time", "report_id", "created_at"),)
    id: Mapped[str] = uuid_column()
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp()
