from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import BaseModel, schema_table_args
from text_to_bi.superset_text_to_bi.modules.auth.models import User
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetDatabase, SupersetDataset

TURN_STATUSES = (
    "running", "answered", "needs_clarification", "cannot_answer", "join_ambiguous", "join_not_declared", "error",
)
TURN_FLOWS = ("metric", "dataset", "none")
FEEDBACK_RATINGS = ("up", "down")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Conversation(BaseModel):
    __tablename__ = "conversations"
    __table_args__ = schema_table_args()

    database_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDatabase.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id: Mapped[int] = Column(Integer, ForeignKey(User.id, ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = Column(String(200), nullable=False, default="", server_default="")
    is_pinned: Mapped[bool] = Column(Boolean, nullable=False, default=False, server_default=false())
    is_archived: Mapped[bool] = Column(Boolean, nullable=False, default=False, server_default=false())
    last_message_at: Mapped[datetime | None] = Column(DateTime(timezone=True), index=True)


class ConversationTurn(BaseModel):
    __tablename__ = "conversation_turns"
    __table_args__ = schema_table_args(
        UniqueConstraint("conversation_id", "sequence", name="uq_conversation_turn_sequence"),
        CheckConstraint(_in("status", TURN_STATUSES), name="status_valid"),
        CheckConstraint(_in("flow", TURN_FLOWS), name="flow_valid"),
    )

    conversation_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(Conversation.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    sequence: Mapped[int] = Column(Integer, nullable=False)
    question: Mapped[str] = Column(Text, nullable=False)
    rewritten_question: Mapped[str | None] = Column(Text)
    answer: Mapped[str | None] = Column(Text)
    flow: Mapped[str | None] = Column(String(16))
    status: Mapped[str] = Column(String(24), nullable=False, default="running", server_default="running")
    steps: Mapped[list[Any] | None] = Column(JSON)
    results: Mapped[list[Any] | None] = Column(JSON)
    rewrite: Mapped[dict[str, Any] | None] = Column(JSON)
    assumptions: Mapped[list[Any] | None] = Column(JSON)
    pii: Mapped[dict[str, Any] | None] = Column(JSON)
    dataset_id: Mapped[int | None] = Column(Integer, ForeignKey(SupersetDataset.id, ondelete="SET NULL"), index=True)
    retry_of: Mapped[UUID | None] = Column(
        PostgresUUID(as_uuid=True), ForeignKey("text_to_bi.conversation_turns.id", ondelete="SET NULL"), index=True,
    )
    error_code: Mapped[str | None] = Column(String(64))
    error_message: Mapped[str | None] = Column(Text)
    duration_ms: Mapped[int | None] = Column(Integer)
    model: Mapped[str | None] = Column(String(100))
    clarification_question: Mapped[str | None] = Column(Text)
    clarification_options: Mapped[list[Any] | None] = Column(JSON)
    continued_from: Mapped[UUID | None] = Column(
        PostgresUUID(as_uuid=True), ForeignKey("text_to_bi.conversation_turns.id", ondelete="SET NULL"), index=True,
    )
    continuation: Mapped[dict[str, Any] | None] = Column(JSON)
    views: Mapped[dict[str, Any] | None] = Column(JSON)


class ConversationTurnFeedback(BaseModel):
    __tablename__ = "conversation_turn_feedback"
    __table_args__ = schema_table_args(
        UniqueConstraint("turn_id", "user_id", name="uq_conversation_turn_feedback_user"),
        CheckConstraint(_in("rating", FEEDBACK_RATINGS), name="rating_valid"),
    )

    turn_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(ConversationTurn.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id: Mapped[int] = Column(Integer, ForeignKey(User.id, ondelete="CASCADE"), nullable=False)
    rating: Mapped[str] = Column(String(8), nullable=False)
    comment: Mapped[str | None] = Column(Text)
