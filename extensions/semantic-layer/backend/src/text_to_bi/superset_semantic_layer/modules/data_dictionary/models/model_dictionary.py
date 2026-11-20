# pyright: reportAssignmentType=false

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, relationship

from text_to_bi.superset_semantic_layer.common.base_model import AuditedModel


class DatasetDictionary(AuditedModel):
    __table_args__ = ({"extend_existing": True},)

    id: Mapped[int] = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), primary_key=True)
    dataset_name: Mapped[str] = Column(String(255), nullable=False)
    display_name: Mapped[str] = Column(String(255), nullable=False)
    description: Mapped[str | None] = Column(Text, nullable=True)
    grain: Mapped[str | None] = Column(Text, nullable=True)
    create_column: Mapped[str | None] = Column(String(255), nullable=True)
    dataset_type: Mapped[str | None] = Column(String(32), nullable=True)
    layer_id: Mapped[int | None] = Column(
        Integer, ForeignKey("text_to_bi_data_layer.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The column that places a row in time, and the one that tells kinds of rows of different grains apart.
    time_column: Mapped[str | None] = Column(String(255), nullable=True)
    row_kind_column: Mapped[str | None] = Column(String(255), nullable=True)
    # Whether the table holds personal data (PII) that consumers must treat as sensitive.
    contains_pii: Mapped[bool] = Column(Boolean, nullable=False, default=False, server_default=false())


class ColumnDictionary(AuditedModel):
    __table_args__ = (
        UniqueConstraint("dataset_id", "column_name", name="uq_text_to_bi_column_dataset_column_name"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)
    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_name: Mapped[str] = Column(String(255), nullable=False)
    display_name: Mapped[str] = Column(String(255), nullable=False)
    data_type: Mapped[str] = Column(String(128), nullable=False)
    nullable: Mapped[bool] = Column(Boolean, nullable=False, default=True)
    default_value: Mapped[str | None] = Column("default", Text, nullable=True)
    is_pk: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    is_fk: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    referenced_column: Mapped[int | None] = Column(
        Integer, ForeignKey("text_to_bi_column_dictionary.id", ondelete="SET NULL"), nullable=True
    )
    is_unique: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    unit: Mapped[str | None] = Column(String(128), nullable=True)
    format: Mapped[str | None] = Column(String(128), nullable=True)
    business_term: Mapped[str | None] = Column(Text, nullable=True)
    # `date` or `timestamp` for a column that places rows in time; a date filter on a timestamp covers the whole day.
    temporal_kind: Mapped[str | None] = Column(String(16), nullable=True)
    # What schema link does with the column (key, measure, dimension, label, time, row_kind, attribute), the
    # aggregations that make sense on a measure and the words people use for it; lists are stored as JSON text.
    semantic_role: Mapped[str | None] = Column(String(16), nullable=True)
    aggregations: Mapped[str | None] = Column(Text, nullable=True)
    synonyms: Mapped[str | None] = Column(Text, nullable=True)
    description: Mapped[str | None] = Column(Text, nullable=True)
    # Whether the column holds personal data (PII) that consumers must treat as sensitive.
    contains_pii: Mapped[bool] = Column(Boolean, nullable=False, default=False, server_default=false())

    referenced_column_record: Mapped["ColumnDictionary | None"] = relationship(
        "ColumnDictionary", remote_side=[id], foreign_keys=[referenced_column], uselist=False
    )
