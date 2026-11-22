# pyright: reportAssignmentType=false

from uuid import UUID

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_column, schema_table_args


class IndicatorAggregation(AuditedModel):
    __tablename__ = "indicator_aggregations"
    __table_args__ = schema_table_args(
        UniqueConstraint("table_dictionary_id", "source_code", name="uq_indicator_aggregations_source_code")
    )

    table_dictionary_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(schema_column("table_dictionaries"), ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_code: Mapped[str] = Column(String(64), nullable=False)
    aggregation: Mapped[str] = Column(String(16), nullable=False)
