from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import ExpertRule


class ExpertRuleRepository(BaseRepository[ExpertRule]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRule)

    # -------------------------READ---------------------------
    def list(self, dataset_id: int) -> list[ExpertRule]:
        statement = select(self.model).where(self.model.dataset_id == dataset_id).order_by(self.model.name)
        return list(self.session.scalars(statement).all())

    def get(self, rule_id: UUID, lock: bool = False) -> ExpertRule | None:
        statement = select(self.model).where(self.model.id == rule_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def find_name(self, dataset_id: int, normalized_name: str) -> ExpertRule | None:
        return self.session.scalar(select(self.model).where(
            self.model.dataset_id == dataset_id, self.model.normalized_name == normalized_name
        ))
