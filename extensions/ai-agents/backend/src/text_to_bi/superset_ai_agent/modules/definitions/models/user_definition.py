from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text

from ....common.base_model import BaseModel


class AgentUserDefinition(BaseModel):
    __table_args__ = ({"extend_existing": True},)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    dashboard_id = Column(Integer, nullable=False, index=True)
    # glossary or expert_rule
    kind = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False)
    concept = Column(String(200), nullable=True)
    definition = Column(Text, nullable=False)
    # For a qualitative concept, the definition as conditions on one dataset, `{dataset_id, filters: [{column, label,
    # operator, value}]}`, worked out when the user confirmed or edited it, so every later question uses the same
    # threshold. NULL when it could not be expressed as conditions; the agent then reads the definition's words.
    conditions = Column(JSON, nullable=True)
    # The question that asked the user, and its conversation.
    source_question_id = Column(Integer, nullable=True)
    source_session_id = Column(Integer, nullable=True)
    review_status = Column(String(20), nullable=False, default="pending", index=True)
    reviewed_by = Column(Integer, nullable=True)
    reviewed_on = Column(DateTime(timezone=True), nullable=True)
    created_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_on = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
