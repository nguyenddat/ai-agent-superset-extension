from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import BaseModel, schema_table_args
from text_to_bi.superset_text_to_bi.modules.auth.models import User
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetDatabase

PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
SUPERSEDED = "superseded"
FINISHED_STATUSES = (SUCCEEDED, FAILED, SUPERSEDED)

EVENT = "event"
SCHEDULE = "schedule"
MANUAL = "manual"


class IngestionJob(BaseModel):
    __tablename__ = "text2sql_ingestion_jobs"
    __table_args__ = schema_table_args(
        Index(
            "uq_text2sql_ingestion_jobs_pending", "database_id", "topic", unique=True,
            postgresql_where=text("status = 'pending'"), sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_text2sql_ingestion_jobs_claim", "status", "run_after"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'superseded')", name="status_valid",
        ),
        CheckConstraint("source IN ('event', 'schedule', 'manual')", name="source_valid"),
    )

    database_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDatabase.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    requested_by_user_id: Mapped[int | None] = Column(
        Integer, ForeignKey(User.id, ondelete="SET NULL"), index=True,
    )
    topic: Mapped[str] = Column(String(32), nullable=False)
    source: Mapped[str] = Column(String(16), nullable=False)
    status: Mapped[str] = Column(String(16), nullable=False, default=PENDING, server_default=PENDING)
    attempts: Mapped[int] = Column(Integer, nullable=False, default=0, server_default="0")
    run_after: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = Column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = Column(DateTime(timezone=True))
    last_error: Mapped[str | None] = Column(Text)
    result: Mapped[dict[str, Any] | None] = Column(JSON)
