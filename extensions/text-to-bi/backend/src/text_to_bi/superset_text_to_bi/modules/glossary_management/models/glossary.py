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


class GlossaryTerm(AuditedModel):
    __tablename__ = "glossary_terms"
    __table_args__ = schema_table_args(UniqueConstraint("dataset_id", "normalized_name", name="uq_glossary_term_name"))

    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_name: Mapped[str] = Column(String(255), nullable=False)
    normalized_name: Mapped[str] = Column(String(255), nullable=False)


glossary_term_domains = Table(
    "glossary_term_domains", BaseModel.metadata,
    Column("term_id", PostgresUUID(as_uuid=True), ForeignKey(schema_column("glossary_terms"), ondelete="CASCADE"),
           primary_key=True),
    Column("domain_id", PostgresUUID(as_uuid=True),
           ForeignKey(schema_column("business_domains"), ondelete="CASCADE"), primary_key=True, index=True),
    schema=TEXT_TO_BI_SCHEMA,
)


class GlossaryRevision(BaseModel):
    __tablename__ = "glossary_revisions"
    __table_args__ = schema_table_args(
        UniqueConstraint("term_id", "number", name="uq_glossary_revision_number"),
        CheckConstraint("status IN ('draft', 'approved', 'revoked')", name="status_valid"),
    )

    term_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(schema_column("glossary_terms"), ondelete="CASCADE"),
        nullable=False, index=True,
    )
    number: Mapped[int] = Column(Integer, nullable=False)
    definition: Mapped[str] = Column(Text, nullable=False)
    synonyms: Mapped[list[str]] = Column(JSON, nullable=False, default=list)
    status: Mapped[str] = Column(String(16), nullable=False, default="draft", server_default="draft")


class GlossaryLink(BaseModel):
    __tablename__ = "glossary_links"
    __table_args__ = schema_table_args(
        CheckConstraint("kind IN ('table', 'column', 'metric', 'superset_metric')", name="kind_valid"),
        UniqueConstraint("revision_id", "kind", "target_key", name="uq_glossary_link_target"),
    )

    revision_id: Mapped[UUID] = Column(PostgresUUID(as_uuid=True), ForeignKey(schema_column("glossary_revisions"),
                                                                             ondelete="CASCADE"), nullable=False,
                                      index=True)
    kind: Mapped[str] = Column(String(32), nullable=False)
    # Stable column identity is dataset ID plus name, rather than table_columns.id.
    target_key: Mapped[str] = Column(String(300), nullable=False)
