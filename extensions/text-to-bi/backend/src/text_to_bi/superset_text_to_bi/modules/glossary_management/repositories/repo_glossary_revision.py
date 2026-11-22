from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import GlossaryRevision


class GlossaryRevisionRepository(BaseRepository[GlossaryRevision]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryRevision)

    # -------------------------READ---------------------------
    def list_by_term(self, term_id: UUID) -> list[GlossaryRevision]:
        statement = select(self.model).where(self.model.term_id == term_id).order_by(self.model.number.desc())
        return list(self.session.scalars(statement).all())
