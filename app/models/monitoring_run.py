from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import MonitoringRunStatus


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[MonitoringRunStatus] = mapped_column(
        Enum(MonitoringRunStatus, native_enum=False, length=32), nullable=False
    )
    items_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    changed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source = relationship("Source", back_populates="monitoring_runs")
