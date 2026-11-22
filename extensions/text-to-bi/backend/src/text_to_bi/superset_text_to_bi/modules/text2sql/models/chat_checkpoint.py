from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, LargeBinary
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import BaseModel, schema_table_args
from text_to_bi.superset_text_to_bi.modules.auth.models import User
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetDatabase


class ChatCheckpoint(BaseModel):
    __tablename__ = "text2sql_chat_checkpoints"
    __table_args__ = schema_table_args()

    database_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDatabase.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id: Mapped[int | None] = Column(Integer, ForeignKey(User.id, ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = Column(
        PostgresUUID(as_uuid=True), ForeignKey("text_to_bi.conversations.id", ondelete="CASCADE"), index=True,
    )
    turn_id: Mapped[UUID | None] = Column(
        PostgresUUID(as_uuid=True), ForeignKey("text_to_bi.conversation_turns.id", ondelete="CASCADE"),
    )
    snapshot: Mapped[bytes] = Column(LargeBinary, nullable=False)
    masked_values: Mapped[dict[str, str] | None] = Column(JSON)
    expires_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, index=True)
