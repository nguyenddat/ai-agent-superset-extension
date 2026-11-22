# pyright: reportAssignmentType=false

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import (
    TEXT_TO_BI_SCHEMA,
    AuditedModel,
    schema_column,
    schema_table_args,
)

from ...data_dictionary.models import SupersetDataset


class Metric(AuditedModel):
    __tablename__ = "metrics"
    __table_args__ = schema_table_args(
        UniqueConstraint("dataset_id", "name", name="uq_metrics_dataset_name"),
        CheckConstraint("status IN ('draft', 'approved', 'revoked')", name="status_valid"),
    )

    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = Column(String(255), nullable=False)
    label: Mapped[str | None] = Column(String(255))
    expression: Mapped[str] = Column(Text, nullable=False)
    description: Mapped[str | None] = Column(Text)
    format: Mapped[str | None] = Column(String(128))
    currency: Mapped[str | None] = Column(String(16))
    metric_type: Mapped[str | None] = Column(String(64))
    warning_text: Mapped[str | None] = Column(Text)
    is_active: Mapped[bool] = Column(Boolean, nullable=False, default=True, server_default=true())
    status: Mapped[str] = Column(String(16), nullable=False, default="draft", server_default="draft")


metric_domains = Table(
    "metric_domains", AuditedModel.metadata,
    Column("metric_id", PostgresUUID(as_uuid=True), ForeignKey(schema_column("metrics"), ondelete="CASCADE"),
           primary_key=True),
    Column("domain_id", PostgresUUID(as_uuid=True),
           ForeignKey(schema_column("business_domains"), ondelete="CASCADE"), primary_key=True, index=True),
    schema=TEXT_TO_BI_SCHEMA,
)
