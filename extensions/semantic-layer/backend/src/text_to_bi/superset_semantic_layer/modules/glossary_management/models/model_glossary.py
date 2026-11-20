# pyright: reportAssignmentType=false

from datetime import datetime

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

# What an audit event records; `moved` is a change of group, which is not a revision of the term.
AUDIT_EVENT_TYPES = "event_type IN ('created', 'updated', 'approved', 'revoked', 'moved')"
LINK_KINDS = "kind IN ('dataset', 'column', 'metric')"


class GlossaryTermGroup(AuditedModel):
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_text_to_bi_glossary_term_group_name"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    name: Mapped[str] = Column(String(255), nullable=False)                                    # Tên nhóm
    normalized_name: Mapped[str] = Column(String(255), nullable=False, index=True)             # Tên chuẩn hóa
    description: Mapped[str | None] = Column(Text, nullable=True)                              # Mô tả


class GlossaryTerm(AuditedModel):
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_text_to_bi_glossary_term_normalized_name"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    canonical_name: Mapped[str] = Column(String(255), nullable=False)                          # Tên thuật ngữ
    normalized_name: Mapped[str] = Column(String(255), nullable=False, index=True)             # Tên chuẩn hóa
    steward_id: Mapped[int | None] = Column(                                                   # Phụ trách
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # The group belongs to the term, not to a revision: moving a term needs no review and keeps it serving.
    group_id: Mapped[int | None] = Column(
        Integer, ForeignKey("text_to_bi_glossary_term_group.id", ondelete="SET NULL"), nullable=True, index=True
    )
    group: Mapped[GlossaryTermGroup | None] = relationship("GlossaryTermGroup")


class GlossaryTermRevision(AuditedModel):
    __table_args__ = (
        UniqueConstraint("term_id", "revision_number", name="uq_text_to_bi_glossary_revision_number"),
        CheckConstraint(ReviewStatus.check(), name="ck_text_to_bi_glossary_revision_status"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    revision_number: Mapped[int] = Column(Integer, nullable=False)                             # Số phiên bản
    definition: Mapped[str] = Column(Text, nullable=False)                                     # Định nghĩa
    synonyms: Mapped[list[str]] = Column(JSON, nullable=False, default=list)                   # Từ đồng nghĩa
    content_hash: Mapped[str] = Column(String(64), nullable=False, index=True)                 # Nội dung hashed
    status: Mapped[str] = Column(                                                              # Trạng thái
        String(16), nullable=False, default=ReviewStatus.DRAFT.value, index=True
    )
    is_current: Mapped[bool] = Column(Boolean, nullable=False, default=True, index=True)       # Bản hiện tại

    # Review
    approver_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)
    revoker_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)

    # Reference
    term_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_glossary_term.id", ondelete="CASCADE"), nullable=False, index=True
    )
    term: Mapped[GlossaryTerm] = relationship("GlossaryTerm")


class GlossaryTermLink(BaseModel):
    __table_args__ = (
        CheckConstraint(LINK_KINDS, name="ck_text_to_bi_glossary_link_kind"),
        UniqueConstraint("revision_id", "link_key", name="uq_text_to_bi_glossary_link"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    kind: Mapped[str] = Column(String(16), nullable=False)                                     # dataset/column/metric
    link_key: Mapped[str] = Column(String(512), nullable=False)
    fingerprint: Mapped[str] = Column(String(64), nullable=False, index=True)                  # Đối tượng hashed

    # Reference
    revision_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_glossary_term_revision.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[int] = Column(Integer, ForeignKey("tables.id", ondelete="CASCADE"), nullable=False, index=True)
    column_name: Mapped[str | None] = Column(String(255), nullable=True)
    metric_id: Mapped[int | None] = Column(
        Integer, ForeignKey("sql_metrics.id", ondelete="CASCADE"), nullable=True, index=True
    )


class GlossaryTermAuditEvent(BaseModel):
    __table_args__ = (
        CheckConstraint(AUDIT_EVENT_TYPES, name="ck_text_to_bi_glossary_audit_event"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)

    event_type: Mapped[str] = Column(String(16), nullable=False, index=True)                   # Hành động
    reason: Mapped[str | None] = Column(String(512), nullable=True)                            # Lý do
    revision_number: Mapped[int] = Column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, index=True)
    actor_id: Mapped[int | None] = Column(
        Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Reference
    term_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_glossary_term.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[int] = Column(
        Integer, ForeignKey("text_to_bi_glossary_term_revision.id", ondelete="CASCADE"), nullable=False, index=True
    )
