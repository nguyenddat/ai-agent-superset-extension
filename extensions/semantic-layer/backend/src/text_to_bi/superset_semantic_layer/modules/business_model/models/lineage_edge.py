from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint

from ....common.base_model import AuditedModel


class LineageEdge(AuditedModel):
    __table_args__ = (
        UniqueConstraint("source_dataset_id", "target_dataset_id", "kind", name="uq_text_to_bi_lineage_edge"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    source_dataset_id = Column(
        Integer,
        ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_dataset_id = Column(
        Integer,
        ForeignKey("text_to_bi_dataset_dictionary.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Reference edges from PK/FK: "flow" when the referenced source sits on an earlier level than the target, else
    # "relation" (source references target, dashed). "transform": target columns are computed from source columns.
    kind = Column(String(16), nullable=False)
    label = Column(String(32), nullable=True)
    is_hidden = Column(Boolean, nullable=False, default=False)
    is_manual = Column(Boolean, nullable=False, default=True)
    color = Column(String(16), nullable=True)
