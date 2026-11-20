# pyright: reportAssignmentType=false

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from text_to_bi.superset_semantic_layer.common.base_model import AuditedModel


class RelationshipContract(AuditedModel):
    __table_args__ = (
        UniqueConstraint("from_dataset_id", "from_column", name="uq_text_to_bi_relationship_contract_from"),
        {"extend_existing": True},
    )
    id: Mapped[int] = Column(Integer, primary_key=True)
    version: Mapped[int] = Column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012
    from_dataset_id: Mapped[int] = Column(
        Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_column: Mapped[str] = Column(String(255), nullable=False)
    to_dataset_id: Mapped[int] = Column(
        Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_column: Mapped[str] = Column(String(255), nullable=False)
    cardinality: Mapped[str] = Column(String(16), nullable=False)
    contract_hash: Mapped[str] = Column(String(64), nullable=False, index=True)
    status: Mapped[str] = Column(String(16), nullable=False, default="candidate", index=True)
    owner_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approver_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)
    revoker_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)
    # Where the relationship was found: `database`, `dictionary` or `naming`.
    source: Mapped[str | None] = Column(String(16), nullable=True)
    verification: Mapped[str | None] = Column(Text, nullable=True)
    verified_hash: Mapped[str | None] = Column(String(64), nullable=True)
    verified_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)
