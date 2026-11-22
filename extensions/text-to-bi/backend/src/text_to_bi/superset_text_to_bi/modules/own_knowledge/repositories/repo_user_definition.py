from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import UserDefinition


class UserDefinitionRepository(BaseRepository[UserDefinition]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, UserDefinition)

    def list_for_dashboard(self, user_id: int, dashboard_id: int) -> list[UserDefinition]:
        statement = select(self.model).where(
            self.model.user_id == user_id, self.model.dashboard_id == dashboard_id,
        ).order_by(self.model.id)
        return list(self.session.scalars(statement).all())

    def get_owned(self, definition_id: UUID, user_id: int) -> UserDefinition | None:
        statement = select(self.model).where(self.model.id == definition_id, self.model.user_id == user_id)
        return self.session.scalar(statement)

    def list_for_review(self) -> list[UserDefinition]:
        statement = select(self.model).order_by(self.model.updated_on.desc(), self.model.id.desc())
        return list(self.session.scalars(statement).all())

    def get_many(self, definition_ids: list[UUID]) -> list[UserDefinition]:
        statement = select(self.model).where(self.model.id.in_(definition_ids))
        return list(self.session.scalars(statement).all())
