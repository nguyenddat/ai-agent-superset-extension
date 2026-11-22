from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import ExpertRuleMetricLink


class ExpertRuleMetricLinkRepository(BaseRepository[ExpertRuleMetricLink]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleMetricLink)

    # -------------------------READ---------------------------
    def list_by_revision(self, revision_id: UUID) -> list[ExpertRuleMetricLink]:
        statement = select(self.model).where(self.model.revision_id == revision_id).order_by(
            self.model.kind, self.model.target_key
        )
        return list(self.session.scalars(statement).all())
