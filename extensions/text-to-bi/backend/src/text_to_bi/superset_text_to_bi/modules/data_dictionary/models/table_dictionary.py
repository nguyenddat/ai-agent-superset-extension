# pyright: reportAssignmentType=false

from uuid import UUID

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_column, schema_table_args

from .superset_catalog import SupersetDataset


class TableDictionary(AuditedModel):
    __tablename__ = "table_dictionaries"
    __table_args__ = schema_table_args(UniqueConstraint("dataset_id", name="uq_table_dictionaries_dataset_id"))

    # Superset's dataset (`tables.id`); the dictionary goes with the dataset.
    dataset_id: Mapped[int] = Column(Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = Column(String(255), nullable=False)
    description: Mapped[str | None] = Column(Text)
    grain_description: Mapped[str | None] = Column(Text)
    table_kind: Mapped[str | None] = Column(String(32))
    layout: Mapped[str] = Column(String(32), nullable=False, default="wide", server_default="wide")
    indicator_catalog_id: Mapped[UUID | None] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(schema_column("table_dictionaries"), ondelete="SET NULL"), index=True
    )
    contains_pii: Mapped[bool] = Column(Boolean, nullable=False, default=False, server_default=false())
