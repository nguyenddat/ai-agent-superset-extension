# pyright: reportAssignmentType=false

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped

from text_to_bi.superset_semantic_layer.common.base_model import AuditedModel


class DatasetGrain(AuditedModel):
    __table_args__ = (
        UniqueConstraint("dataset_id", "row_kind_value", name="uq_text_to_bi_dataset_grain_row_kind"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)
    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_kind_value: Mapped[str | None] = Column(String(255), nullable=True)
    label: Mapped[str | None] = Column(String(255), nullable=True)
    grain: Mapped[str] = Column(String(16), nullable=False)
