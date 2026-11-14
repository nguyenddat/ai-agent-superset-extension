# pyright: reportAssignmentType=false

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped

from text_to_bi.superset_semantic_layer.common.base_model import BaseModel

# What a grouping suggestion gathers: glossary terms or expert rules.
SUGGESTION_KINDS = "kind IN ('glossary', 'expert_rule')"


class TextEmbedding(BaseModel):
    """A text's vector from a remote embedding model, kept by the text's hash so unchanged text is not embedded again.

    Glossary terms and expert rules share it: the key is the text itself, not the term or rule it describes.
    """

    __table_args__ = (
        UniqueConstraint("model", "content_hash", name="uq_text_to_bi_text_embedding"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)
    model: Mapped[str] = Column(String(255), nullable=False)
    content_hash: Mapped[str] = Column(String(64), nullable=False)
    vector: Mapped[Any] = Column(JSON, nullable=False)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)


class GroupSuggestionDismissal(BaseModel):
    """A grouping suggestion an administrator dismissed, by its fingerprint: the target group and the members.

    The same suggestion is not offered again; one that gains or loses a member has another fingerprint and is.
    """

    __table_args__ = (
        CheckConstraint(SUGGESTION_KINDS, name="ck_text_to_bi_group_suggestion_dismissal_kind"),
        UniqueConstraint("kind", "fingerprint", name="uq_text_to_bi_group_suggestion_dismissal"),
        {"extend_existing": True},
    )

    id: Mapped[int] = Column(Integer, primary_key=True)
    kind: Mapped[str] = Column(String(16), nullable=False)
    fingerprint: Mapped[str] = Column(String(64), nullable=False)
    dismissed_by: Mapped[int | None] = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
    dismissed_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
