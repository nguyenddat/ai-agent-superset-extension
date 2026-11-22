# pyright: reportAssignmentType=false

from uuid import UUID

from sqlalchemy import Column, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_column, schema_table_args


class TableTimeGrain(AuditedModel):
    __tablename__ = "table_time_grains"

    table_dictionary_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(schema_column("table_dictionaries"), ondelete="CASCADE"),
        nullable=False, index=True,
    )
    row_kind_value: Mapped[str | None] = Column(String(255))
    label: Mapped[str | None] = Column(String(255))
    time_grain: Mapped[str] = Column(String(16), nullable=False)

    __table_args__ = schema_table_args(
        Index(
            "uq_table_time_grains_row_kind", table_dictionary_id, func.coalesce(row_kind_value, ""), unique=True
        ),
    )
