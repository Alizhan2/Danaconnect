"""Read receipts are explicit per message; a time cursor cannot consume arrivals."""
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, timestamp, uuid_column


class MessageRead(Base):
    __tablename__ = "message_reads"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uq_message_read_user_message"),)
    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime] = timestamp()
