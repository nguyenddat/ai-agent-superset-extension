# pyright: reportAssignmentType=false

from uuid import UUID

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_column, schema_table_args


class ColumnAggregation(AuditedModel):
    __tablename__ = "column_aggregations"
    __table_args__ = schema_table_args(
        UniqueConstraint("column_dictionary_id", "aggregation", name="uq_column_aggregations_aggregation")
    )

    column_dictionary_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(schema_column("column_dictionaries"), ondelete="CASCADE"),
        nullable=False, index=True,
    )
    aggregation: Mapped[str] = Column(String(16), nullable=False)
