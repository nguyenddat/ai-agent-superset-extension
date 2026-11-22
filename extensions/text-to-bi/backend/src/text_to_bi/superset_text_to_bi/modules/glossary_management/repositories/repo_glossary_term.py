from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import GlossaryTerm


class GlossaryTermRepository(BaseRepository[GlossaryTerm]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTerm)

    # -------------------------READ---------------------------
    def list(self, dataset_id: int) -> list[GlossaryTerm]:
        statement = select(self.model).where(self.model.dataset_id == dataset_id).order_by(self.model.canonical_name)
        return list(self.session.scalars(statement).all())

    def get(self, term_id: UUID, lock: bool = False) -> GlossaryTerm | None:
        statement = select(self.model).where(self.model.id == term_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def find_name(self, dataset_id: int, normalized_name: str) -> GlossaryTerm | None:
        return self.session.scalar(select(self.model).where(
            self.model.dataset_id == dataset_id, self.model.normalized_name == normalized_name
        ))
