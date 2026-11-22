from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, BaseModel, schema_table_args
from text_to_bi.superset_text_to_bi.modules.auth.models import User
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetDataset


class OwnClarification(BaseModel):
    __tablename__ = "own_knowledge_clarifications"
    __table_args__ = schema_table_args(
        UniqueConstraint("dataset_id", "user_id", "idempotency_key", name="uq_own_clarification_key"),
        CheckConstraint("status IN ('pending', 'confirmed', 'dismissed')", name="status_valid"),
    )

    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id: Mapped[int] = Column(Integer, ForeignKey(User.id, ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key: Mapped[str] = Column(String(128), nullable=False)
    source_session_id: Mapped[str | None] = Column(String(255))
    source_question_id: Mapped[str | None] = Column(String(255))
    question: Mapped[str] = Column(Text, nullable=False)
    missing: Mapped[list[str]] = Column(JSON, nullable=False)
    status: Mapped[str] = Column(String(16), nullable=False, default="pending")
    request_fingerprint: Mapped[str] = Column(String(64), nullable=False)
    answer_fingerprint: Mapped[str | None] = Column(String(64))
    confirmed_entry_ids: Mapped[list[str]] = Column(JSON, nullable=False, default=list)
    answered_at: Mapped[datetime | None] = Column(DateTime(timezone=True))


class OwnProposal(BaseModel):
    __tablename__ = "own_knowledge_proposals"
    __table_args__ = schema_table_args(
        UniqueConstraint("clarification_id", "kind", "normalized_name", name="uq_own_proposal_name"),
        CheckConstraint("kind IN ('glossary', 'metric', 'expert_rule')", name="kind_valid"),
    )

    clarification_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(OwnClarification.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    kind: Mapped[str] = Column(String(20), nullable=False)
    name: Mapped[str] = Column(String(255), nullable=False)
    normalized_name: Mapped[str] = Column(String(255), nullable=False)
    concept: Mapped[str | None] = Column(String(255))
    prompt: Mapped[str] = Column(Text, nullable=False)
    options: Mapped[list[str]] = Column(JSON, nullable=False)
    dataset_id: Mapped[int | None] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="SET NULL"), index=True,
    )


class OwnKnowledgeEntry(AuditedModel):
    __tablename__ = "own_knowledge_entries"
    __table_args__ = schema_table_args(
        UniqueConstraint("dataset_id", "user_id", "kind", "normalized_name", name="uq_own_entry_name"),
        CheckConstraint("kind IN ('glossary', 'metric', 'expert_rule')", name="kind_valid"),
        CheckConstraint("review_status IN ('pending', 'kept_own', 'promoted')", name="review_status_valid"),
    )

    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id: Mapped[int] = Column(Integer, ForeignKey(User.id, ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = Column(String(20), nullable=False)
    name: Mapped[str] = Column(String(255), nullable=False)
    normalized_name: Mapped[str] = Column(String(255), nullable=False)
    concept: Mapped[str | None] = Column(String(255))
    definition: Mapped[str] = Column(Text, nullable=False)
    version: Mapped[int] = Column(Integer, nullable=False, default=1, server_default="1")
    source_clarification_id: Mapped[UUID | None] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(OwnClarification.id, ondelete="SET NULL"), index=True,
    )
    source_proposal_id: Mapped[UUID | None] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(OwnProposal.id, ondelete="SET NULL"), index=True,
    )
    review_status: Mapped[str] = Column(String(16), nullable=False, default="pending", index=True)
    review_note: Mapped[str | None] = Column(Text)
    reviewed_by: Mapped[int | None] = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = Column(DateTime(timezone=True))
    promoted_kind: Mapped[str | None] = Column(String(20))
    promoted_id: Mapped[UUID | None] = Column(PostgresUUID(as_uuid=True))
