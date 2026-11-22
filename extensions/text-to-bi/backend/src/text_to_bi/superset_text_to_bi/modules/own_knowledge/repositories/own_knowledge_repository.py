from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import OwnClarification, OwnKnowledgeEntry, OwnProposal


class OwnClarificationRepository(BaseRepository[OwnClarification]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, OwnClarification)

    def get(self, clarification_id: UUID, lock: bool = False) -> OwnClarification | None:
        statement = select(self.model).where(self.model.id == clarification_id)
        return self.session.scalar(statement.with_for_update() if lock else statement)

    def by_key(self, dataset_id: int, user_id: int, key: str) -> OwnClarification | None:
        return self.session.scalar(select(self.model).where(
            self.model.dataset_id == dataset_id, self.model.user_id == user_id, self.model.idempotency_key == key,
        ))


class OwnProposalRepository(BaseRepository[OwnProposal]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, OwnProposal)

    def list_for_clarification(self, clarification_id: UUID) -> list[OwnProposal]:
        statement = select(self.model).where(self.model.clarification_id == clarification_id).order_by(self.model.id)
        return list(self.session.scalars(statement).all())


class OwnKnowledgeEntryRepository(BaseRepository[OwnKnowledgeEntry]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, OwnKnowledgeEntry)

    def get(self, entry_id: UUID, lock: bool = False) -> OwnKnowledgeEntry | None:
        statement = select(self.model).where(self.model.id == entry_id)
        return self.session.scalar(statement.with_for_update() if lock else statement)

    def own_entry(self, dataset_id: int, user_id: int, kind: str, normalized_name: str) -> OwnKnowledgeEntry | None:
        return self.session.scalar(select(self.model).where(
            self.model.dataset_id == dataset_id, self.model.user_id == user_id,
            self.model.kind == kind, self.model.normalized_name == normalized_name,
        ))

    def own_entries(self, dataset_id: int, user_id: int) -> list[OwnKnowledgeEntry]:
        statement = select(self.model).where(
            self.model.dataset_id == dataset_id, self.model.user_id == user_id,
        ).order_by(self.model.name, self.model.id)
        return list(self.session.scalars(statement).all())

    def review_entries(
        self, dataset_id: int | None, status: str | None, user_id: int | None,
    ) -> list[OwnKnowledgeEntry]:
        statement = select(self.model)
        if dataset_id is not None:
            statement = statement.where(self.model.dataset_id == dataset_id)
        if status is not None:
            statement = statement.where(self.model.review_status == status)
        if user_id is not None:
            statement = statement.where(self.model.user_id == user_id)
        statement = statement.order_by(self.model.updated_at.desc(), self.model.id)
        return list(self.session.scalars(statement).all())


class OwnKnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self.clarifications = OwnClarificationRepository(session)
        self.proposals = OwnProposalRepository(session)
        self.entries = OwnKnowledgeEntryRepository(session)

