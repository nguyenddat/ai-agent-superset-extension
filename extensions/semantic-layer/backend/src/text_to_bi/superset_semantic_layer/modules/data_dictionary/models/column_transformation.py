from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint

from ....common.base_model import AuditedModel


class ColumnTransformation(AuditedModel):
    """How an administrator declares a column is computed from columns of other tables, as a metric is from its inputs.

    ``expression`` is free text (SQL or pseudo code) shown as written and never parsed; the inputs are the explicit
    ``ColumnTransformationSource`` rows.
    """

    __table_args__ = ({"extend_existing": True},)

    column_id = Column(
        Integer, ForeignKey("text_to_bi_column_dictionary.id", ondelete="CASCADE"), primary_key=True,
    )
    expression = Column(Text, nullable=True)


class ColumnTransformationSource(AuditedModel):
    """One input column of a declared transformation, in the order the administrator listed it."""

    __table_args__ = (
        UniqueConstraint("column_id", "source_column_id", name="uq_text_to_bi_column_transformation_source"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    column_id = Column(
        Integer,
        ForeignKey("text_to_bi_column_transformation.column_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_column_id = Column(
        Integer, ForeignKey("text_to_bi_column_dictionary.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    position = Column(Integer, nullable=False, default=0)
