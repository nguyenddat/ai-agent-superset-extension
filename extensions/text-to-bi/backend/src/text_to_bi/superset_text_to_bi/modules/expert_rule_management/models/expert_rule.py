# pyright: reportAssignmentType=false

from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import (
    TEXT_TO_BI_SCHEMA,
    AuditedModel,
    BaseModel,
    schema_column,
    schema_table_args,
)
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetDataset
from text_to_bi.superset_text_to_bi.modules.glossary_management.models import GlossaryRevision, GlossaryTerm


class ExpertRule(AuditedModel):
    __tablename__ = "expert_rules"
    __table_args__ = schema_table_args(UniqueConstraint("dataset_id", "normalized_name", name="uq_expert_rule_name"))

    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = Column(String(255), nullable=False)
    normalized_name: Mapped[str] = Column(String(255), nullable=False)


expert_rule_domains = Table(
    "expert_rule_domains", BaseModel.metadata,
    Column("rule_id", PostgresUUID(as_uuid=True), ForeignKey(ExpertRule.id, ondelete="CASCADE"),
           primary_key=True),
    Column("domain_id", PostgresUUID(as_uuid=True),
           ForeignKey(schema_column("business_domains"), ondelete="CASCADE"), primary_key=True, index=True),
    schema=TEXT_TO_BI_SCHEMA,
)


class ExpertRuleRevision(BaseModel):
    __tablename__ = "expert_rule_revisions"
    __table_args__ = schema_table_args(
        UniqueConstraint("rule_id", "number", name="uq_expert_rule_revision_number"),
        CheckConstraint("status IN ('draft', 'approved', 'revoked')", name="status_valid"),
    )

    rule_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(ExpertRule.id, ondelete="CASCADE"),
        nullable=False, index=True,
    )
    number: Mapped[int] = Column(Integer, nullable=False)
    description: Mapped[str | None] = Column(Text)
    conditions: Mapped[list[dict]] = Column(JSON, nullable=False, default=list)
    exceptions: Mapped[list[dict]] = Column(JSON, nullable=False, default=list)
    examples: Mapped[list[dict]] = Column(JSON, nullable=False, default=list)
    status: Mapped[str] = Column(String(16), nullable=False, default="draft", server_default="draft")


class ExpertRuleGlossaryLink(BaseModel):
    __tablename__ = "expert_rule_glossary_links"
    __table_args__ = schema_table_args(UniqueConstraint("revision_id", "term_id", name="uq_rule_glossary_link"))

    revision_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(ExpertRuleRevision.id, ondelete="CASCADE"), nullable=False
    )
    term_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(GlossaryTerm.id, ondelete="CASCADE"), nullable=False
    )
    glossary_revision_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(GlossaryRevision.id, ondelete="CASCADE"), nullable=False
    )


class ExpertRuleMetricLink(BaseModel):
    __tablename__ = "expert_rule_metric_links"
    __table_args__ = schema_table_args(
        UniqueConstraint("revision_id", "kind", "target_key", name="uq_rule_metric_link")
    )

    revision_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(ExpertRuleRevision.id, ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = Column(String(32), nullable=False)
    target_key: Mapped[str] = Column(String(40), nullable=False)
    fingerprint: Mapped[str] = Column(String(64), nullable=False)
