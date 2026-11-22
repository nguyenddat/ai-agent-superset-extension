from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import BaseModel, schema_table_args
from text_to_bi.superset_text_to_bi.common.utils.type_formatters import utc_now
from text_to_bi.superset_text_to_bi.modules.auth.models import User


class UserDefinition(BaseModel):
    __tablename__ = "user_definitions"
    __table_args__ = schema_table_args(
        UniqueConstraint("user_id", "dashboard_id", "kind", "normalized_name", name="uq_user_definition_name"),
    )

    user_id: Mapped[int] = Column(Integer, ForeignKey(User.id, ondelete="CASCADE"), nullable=False, index=True)
    dashboard_id: Mapped[int] = Column(
        Integer, ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    kind: Mapped[str] = Column(String(20), nullable=False)
    name: Mapped[str] = Column(String(200), nullable=False)
    normalized_name: Mapped[str] = Column(String(200), nullable=False)
    concept: Mapped[str | None] = Column(String(200))
    definition: Mapped[str] = Column(Text, nullable=False)
    conditions: Mapped[list[dict] | None] = Column(JSON)
    # The question/session modules are migrated separately; these IDs remain optional references until then.
    source_question_id: Mapped[int | None] = Column(Integer)
    source_session_id: Mapped[int | None] = Column(Integer)
    review_status: Mapped[str] = Column(String(20), nullable=False, default="pending", index=True)
    reviewed_by: Mapped[int | None] = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    reviewed_on: Mapped[datetime | None] = Column(DateTime(timezone=True))
    created_on: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now(),
    )
    updated_on: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )
