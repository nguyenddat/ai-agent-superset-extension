# pyright: reportAssignmentType=false

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, relationship

from text_to_bi.superset_semantic_layer.common.base_model import AuditedModel, BaseModel
from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus

EVENT_ACTIONS = "action IN ('candidate', 'approve', 'revoke', 'definition')"


class MetricDefinition(BaseModel):
    __table_args__ = (
        UniqueConstraint("metric_id", name="uq_text_to_bi_metric_definition_metric"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    unit: Mapped[str | None] = Column(String(64), nullable=True)                               # Đơn vị
    business_definition: Mapped[str] = Column(Text, nullable=False)                            # Định nghĩa nghiệp vụ
    steward_id: Mapped[int | None] = Column(                                                   # Phụ trách
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Query defaults, used unless a question says otherwise; changing them voids an approval like a formula edit
    grain: Mapped[str | None] = Column(String(16), nullable=True)                              # Grain
    row_kind_value: Mapped[str | None] = Column(String(255), nullable=True)                    # Loại dòng
    time_column: Mapped[str | None] = Column(String(255), nullable=True)                       # Cột thời gian
    time_window: Mapped[str | None] = Column(String(32), nullable=True)                        # Khoảng thời gian
    time_anchor: Mapped[str | None] = Column(String(16), nullable=True)                        # now / latest_data
    default_filters: Mapped[str | None] = Column(Text, nullable=True)                          # JSON bộ lọc mặc định

    # Reference
    metric_id: Mapped[int] = Column(Integer, ForeignKey("sql_metrics.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[int] = Column(
        Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True
    )


class MetricContract(AuditedModel):
    __table_args__ = (
        UniqueConstraint("definition_id", name="uq_text_to_bi_metric_contract_definition"),
        CheckConstraint(ReviewStatus.check(), name="ck_text_to_bi_metric_contract_status"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    metric_name: Mapped[str] = Column(String(255), nullable=False)                             # Tên metric
    expression: Mapped[str] = Column(Text, nullable=False)                                     # Công thức
    expression_hash: Mapped[str] = Column(String(64), nullable=False, index=True)              # Công thức hashed
    status: Mapped[str] = Column(                                                              # Trạng thái
        String(16), nullable=False, default=ReviewStatus.DRAFT.value, index=True
    )

    # `ai_agent` for a metric the AI Agent built from an aggregate dataset: its draft may answer the asker as a
    # provisional figure until an administrator approves it; `manual` drafts only run as an administrator preview.
    origin: Mapped[str] = Column(String(16), nullable=False, default="manual")
    owner_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approver_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revoker_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    approved_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)

    # Reference
    definition_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_metric_definition.id", ondelete="CASCADE"), nullable=False
    )
    definition: Mapped[MetricDefinition] = relationship(MetricDefinition, lazy="joined")

    @property
    def dataset_id(self) -> int:
        return self.definition.dataset_id

    @property
    def metric_id(self) -> int:
        return self.definition.metric_id


class MetricContractEvent(BaseModel):
    __table_args__ = (
        CheckConstraint(EVENT_ACTIONS, name="ck_text_to_bi_metric_event_action"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    action: Mapped[str] = Column(String(16), nullable=False)                                   # Hành động
    actor_id: Mapped[int | None] = Column(                                                     # Người làm
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason: Mapped[str | None] = Column(Text, nullable=True)                                   # Lý do
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)             # Thời điểm

    # Snapshot at the time of the event, kept after the metric is deleted
    metric_name: Mapped[str] = Column(String(255), nullable=False)                             # Tên metric
    expression: Mapped[str | None] = Column(Text, nullable=True)                               # Công thức
    expression_hash: Mapped[str | None] = Column(String(64), nullable=True)                    # Hash
    definition_snapshot: Mapped[dict[str, Any] | None] = Column(JSON, nullable=True)           # Định nghĩa + mặc định

    # Reference: SET NULL and plain IDs, so the history outlives the metric
    metric_id: Mapped[int | None] = Column(Integer, nullable=True, index=True)
    dataset_id: Mapped[int | None] = Column(Integer, nullable=True, index=True)
    definition_id: Mapped[int | None] = Column(
        Integer, ForeignKey("text_to_bi_metric_definition.id", ondelete="SET NULL"), nullable=True, index=True
    )
