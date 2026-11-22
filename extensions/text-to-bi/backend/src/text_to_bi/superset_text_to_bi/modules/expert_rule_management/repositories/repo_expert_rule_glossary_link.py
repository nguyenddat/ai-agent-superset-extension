from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import ExpertRuleGlossaryLink


class ExpertRuleGlossaryLinkRepository(BaseRepository[ExpertRuleGlossaryLink]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleGlossaryLink)

    # -------------------------READ---------------------------
    def list_by_revision(self, revision_id: UUID) -> list[ExpertRuleGlossaryLink]:
        statement = select(self.model).where(self.model.revision_id == revision_id).order_by(self.model.term_id)
        return list(self.session.scalars(statement).all())
