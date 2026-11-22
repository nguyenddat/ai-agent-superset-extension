from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import ExpertRuleRevision


class ExpertRuleRevisionRepository(BaseRepository[ExpertRuleRevision]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleRevision)

    # -------------------------READ---------------------------
    def list_by_rule(self, rule_id: UUID) -> list[ExpertRuleRevision]:
        statement = select(self.model).where(self.model.rule_id == rule_id).order_by(self.model.number.desc())
        return list(self.session.scalars(statement).all())
