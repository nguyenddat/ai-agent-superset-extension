# pyright: reportAssignmentType=false

from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from text_to_bi.superset_semantic_layer.common.base_model import AuditedModel


class ColumnTransformation(AuditedModel):
    __table_args__ = ({"extend_existing": True},)

    column_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_column_dictionary.id", ondelete="CASCADE"), primary_key=True
    )
    expression: Mapped[str | None] = Column(Text, nullable=True)


class ColumnTransformationSource(AuditedModel):
    __table_args__ = (
        UniqueConstraint("column_id", "source_column_id", name="uq_text_to_bi_column_transformation_source"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)
    column_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_column_transformation.column_id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    source_column_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_column_dictionary.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = Column(Integer, nullable=False, default=0)
