from datetime import datetime
from sqlalchemy import CheckConstraint, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models import Base, UTCDateTime


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (CheckConstraint("status IN ('idle','running','success','failed')", name="ck_worker_status"),)
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="idle")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
