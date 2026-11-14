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

from text_to_bi.superset_semantic_layer.common.base_model import BaseModel


class Contradiction(BaseModel):
    """A contradiction between glossary terms, expert rules and metrics, or inside one rule, for an administrator.

    `pair_key` names the kind and the items, so each check finds the same row again. `fingerprint` hashes the items'
    content: a dismissal holds while it is unchanged, and a check that finds changed content opens the row again.
    """

    __table_args__ = (
        UniqueConstraint("pair_key", name="uq_text_to_bi_contradiction_pair_key"),
        CheckConstraint("status IN ('open', 'dismissed')", name="ck_text_to_bi_contradiction_status"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(32), nullable=False, index=True)
    pair_key = Column(String(255), nullable=False)
    # Each item's type (term, rule, metric), ID and name when found.
    items = Column(JSON, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    evidence = Column(JSON, nullable=False)
    explanation = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="open", index=True)
    dismiss_reason = Column(String(512), nullable=True)
    dismissed_by = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False)


class ContradictionJudgement(BaseModel):
    """The AI model's verdict on one pair's content, kept so an unchanged pair is never judged again."""

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_text_to_bi_contradiction_judgement_fingerprint"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    fingerprint = Column(String(64), nullable=False)
    contradiction = Column(Boolean, nullable=False)
    explanation = Column(Text, nullable=True)
    judged_at = Column(DateTime(timezone=True), nullable=False)
