# pyright: reportAssignmentType=false

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_table_args

from .superset_catalog import SupersetDataset


# A column's dictionary, keyed by (dataset, column name) because Superset may delete and recreate `table_columns`
# rows when a dataset is synced. Type, nullability and the temporal flag are read from Superset's TableColumn.
class ColumnDictionary(AuditedModel):
    __tablename__ = "column_dictionaries"
    __table_args__ = schema_table_args(
        UniqueConstraint("dataset_id", "column_name", name="uq_column_dictionaries_dataset_column")
    )

    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True
    )
    column_name: Mapped[str] = Column(String(255), nullable=False)
    display_name: Mapped[str] = Column(String(255), nullable=False)
    description: Mapped[str | None] = Column(Text)
    business_term: Mapped[str | None] = Column(Text)
    semantic_role: Mapped[str | None] = Column(String(16))
    temporal_kind: Mapped[str | None] = Column(String(16))
    unit: Mapped[str | None] = Column(String(128))
    format: Mapped[str | None] = Column(String(128))
    # Null: the column is a key when its name looks like one; Superset does not record primary keys.
    is_primary_key: Mapped[bool | None] = Column(Boolean)
    is_unique: Mapped[bool] = Column(Boolean, nullable=False, default=False, server_default=false())
    # The column this one refers to (a logical foreign key), named like the column itself.
    referenced_dataset_id: Mapped[int | None] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="SET NULL"), index=True
    )
    referenced_column_name: Mapped[str | None] = Column(String(255))
    contains_pii: Mapped[bool] = Column(Boolean, nullable=False, default=False, server_default=false())
