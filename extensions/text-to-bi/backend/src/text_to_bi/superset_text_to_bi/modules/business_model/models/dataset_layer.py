from uuid import UUID

from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import BaseModel, schema_column, schema_table_args


class DatasetLayer(BaseModel):
    __tablename__ = "dataset_layers"
    __table_args__ = schema_table_args(UniqueConstraint("dataset_id", name="uq_dataset_layers_dataset_id"))
    dataset_id: Mapped[int] = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    layer_id: Mapped[UUID | None] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(schema_column("data_layers"), ondelete="SET NULL")
    )
