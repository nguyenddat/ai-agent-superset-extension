# pyright: reportAssignmentType=false

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, relationship

from text_to_bi.superset_semantic_layer.common.base_model import AuditedModel, BaseModel
from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus

# What an audit event records; `moved` is a change of group, which is not a revision of the rule.
AUDIT_EVENT_TYPES = "event_type IN ('created', 'updated', 'approved', 'revoked', 'moved')"
LINK_KINDS = "kind IN ('dataset', 'glossary', 'metric')"


class ExpertRuleGroup(AuditedModel):
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_text_to_bi_expert_rule_group_name"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    name: Mapped[str] = Column(String(255), nullable=False)                                    # Tên nhóm
    normalized_name: Mapped[str] = Column(String(255), nullable=False, index=True)             # Tên chuẩn hóa
    description: Mapped[str | None] = Column(Text, nullable=True)                              # Mô tả


class ExpertRule(AuditedModel):
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_text_to_bi_expert_rule_name"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    normalized_name: Mapped[str] = Column(String(255), nullable=False, index=True)             # Tên chuẩn hóa

    # Reference
    dataset_id: Mapped[int] = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    # The group belongs to the rule, not to a revision: moving a rule needs no review and keeps it discoverable.
    group_id: Mapped[int | None] = Column(
        Integer, ForeignKey("text_to_bi_expert_rule_group.id", ondelete="SET NULL"), nullable=True, index=True
    )
    group: Mapped[ExpertRuleGroup | None] = relationship("ExpertRuleGroup")


class ExpertRuleRevision(AuditedModel):
    __table_args__ = (
        UniqueConstraint("rule_id", "revision_number", name="uq_text_to_bi_expert_rule_revision"),
        CheckConstraint(ReviewStatus.check(), name="ck_text_to_bi_expert_rule_status"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    revision_number: Mapped[int] = Column(Integer, nullable=False)                             # Số phiên bản
    # Optimistic-concurrency token. It differs from revision_number because approve/revoke change no content.
    lifecycle_version: Mapped[int] = Column(Integer, nullable=False, default=1)
    name: Mapped[str] = Column(String(255), nullable=False)                                    # Tên rule
    conditions: Mapped[list[dict[str, Any]]] = Column(JSON, nullable=False)                    # Điều kiện
    exceptions: Mapped[list[dict[str, Any]]] = Column(JSON, nullable=False)                    # Ngoại lệ
    examples: Mapped[list[dict[str, Any]]] = Column(JSON, nullable=False)                      # Câu hỏi ví dụ
    content_hash: Mapped[str] = Column(String(64), nullable=False, index=True)                 # Nội dung hashed
    status: Mapped[str] = Column(                                                              # Trạng thái
        String(16), nullable=False, default=ReviewStatus.DRAFT.value, index=True
    )
    is_current: Mapped[bool] = Column(Boolean, nullable=False, default=True, index=True)       # Bản hiện tại

    # Review
    approver_id: Mapped[int | None] = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)
    revoker_id: Mapped[int | None] = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    revoked_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)

    # Reference
    rule_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_expert_rule.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule: Mapped[ExpertRule] = relationship("ExpertRule")


class ExpertRuleLink(BaseModel):
    __table_args__ = (
        CheckConstraint(LINK_KINDS, name="ck_text_to_bi_expert_rule_link_kind"),
        UniqueConstraint("revision_id", "kind", "target_id", name="uq_text_to_bi_expert_rule_link"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    kind: Mapped[str] = Column(String(16), nullable=False)                                     # dataset/glossary/metric
    target_id: Mapped[int] = Column(Integer, nullable=False)
    fingerprint: Mapped[str] = Column(String(64), nullable=False, index=True)                  # Đối tượng hashed

    # Reference
    revision_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_expert_rule_revision.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[int] = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)


class ExpertRuleAuditEvent(BaseModel):
    __table_args__ = (
        CheckConstraint(AUDIT_EVENT_TYPES, name="ck_text_to_bi_expert_rule_audit"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    event_type: Mapped[str] = Column(String(16), nullable=False, index=True)                   # Hành động
    reason: Mapped[str | None] = Column(String(512), nullable=True)                            # Lý do
    revision_number: Mapped[int] = Column(Integer, nullable=False)
    lifecycle_version: Mapped[int] = Column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, index=True)
    actor_id: Mapped[int | None] = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)

    # Audit history follows the rule when its dataset is deleted.
    rule_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_expert_rule.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_expert_rule_revision.id", ondelete="CASCADE"), nullable=False, index=True
    )
