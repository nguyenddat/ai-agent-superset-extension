from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_table_args

from ...data_dictionary.models import SupersetDataset


class LineageEdge(AuditedModel):
    __tablename__ = "lineage_edges"
    __table_args__ = schema_table_args(
        UniqueConstraint("source_dataset_id", "target_dataset_id", "kind", name="uq_lineage_edges_key"),
        CheckConstraint("kind IN ('flow', 'relation', 'transform')", name="kind_valid"),
    )

    source_dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True
    )
    target_dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = Column(String(16), nullable=False)
    label: Mapped[str | None] = Column(String(255))
    color: Mapped[str | None] = Column(String(16))
    is_hidden: Mapped[bool] = Column(Boolean, nullable=False, default=False, server_default=false())
    is_manual: Mapped[bool] = Column(Boolean, nullable=False, default=True, server_default=true())
