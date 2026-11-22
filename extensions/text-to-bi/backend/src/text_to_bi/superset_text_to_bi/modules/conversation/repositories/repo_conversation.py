from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import Conversation, ConversationTurn, ConversationTurnFeedback


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Conversation)
        self.session = session

    def conversation(self, conversation_id: UUID, lock: bool = False) -> Conversation | None:
        statement = select(Conversation).where(Conversation.id == conversation_id)
        return self.session.scalar(statement.with_for_update() if lock else statement)

    def list_page(
        self, user_id: int, database_id: int | None, archived: bool, query: str | None, limit: int, offset: int,
    ) -> list[Conversation]:
        statement = select(Conversation).where(
            Conversation.user_id == user_id, Conversation.is_archived.is_(archived),
        )
        if database_id is not None:
            statement = statement.where(Conversation.database_id == database_id)
        if query:
            statement = statement.where(Conversation.title.ilike(f"%{_escape_like(query)}%", escape="\\"))
        statement = statement.order_by(
            Conversation.is_pinned.desc(), Conversation.last_message_at.desc().nulls_last(),
            Conversation.created_at.desc(), Conversation.id.desc(),
        ).offset(offset).limit(limit)
        return list(self.session.scalars(statement).all())

    def turn_counts(self, conversation_ids: Iterable[UUID]) -> dict[UUID, int]:
        ids = list(conversation_ids)
        if not ids:
            return {}
        rows = self.session.execute(
            select(ConversationTurn.conversation_id, func.count())
            .where(ConversationTurn.conversation_id.in_(ids)).group_by(ConversationTurn.conversation_id)
        )
        return {conversation_id: count for conversation_id, count in rows}

    def last_turns(self, conversation_ids: Iterable[UUID]) -> dict[UUID, ConversationTurn]:
        ids = list(conversation_ids)
        if not ids:
            return {}
        latest = (
            select(ConversationTurn.conversation_id, func.max(ConversationTurn.sequence))
            .where(ConversationTurn.conversation_id.in_(ids)).group_by(ConversationTurn.conversation_id)
        )
        turns = self.session.scalars(select(ConversationTurn).where(
            tuple_(ConversationTurn.conversation_id, ConversationTurn.sequence).in_(latest)
        ))
        return {turn.conversation_id: turn for turn in turns}

    def turn_count(self, conversation_id: UUID) -> int:
        return self.turn_counts([conversation_id]).get(conversation_id, 0)

    def next_sequence(self, conversation_id: UUID) -> int:
        current = self.session.scalar(
            select(func.max(ConversationTurn.sequence)).where(ConversationTurn.conversation_id == conversation_id)
        )
        return (current or 0) + 1

    def turns(self, conversation_id: UUID, limit: int, offset: int) -> list[ConversationTurn]:
        return list(self.session.scalars(
            select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.sequence).offset(offset).limit(limit)
        ).all())

    def turn(self, conversation_id: UUID, turn_id: UUID) -> ConversationTurn | None:
        return self.session.scalar(select(ConversationTurn).where(
            ConversationTurn.id == turn_id, ConversationTurn.conversation_id == conversation_id,
        ))

    def recent_turns(self, conversation_id: UUID, statuses: Iterable[str], limit: int) -> list[ConversationTurn]:
        rows = self.session.scalars(
            select(ConversationTurn).where(
                ConversationTurn.conversation_id == conversation_id, ConversationTurn.status.in_(list(statuses)),
            ).order_by(ConversationTurn.sequence.desc()).limit(limit)
        )
        return list(reversed(list(rows)))

    def user_questions(self, user_id: int, database_id: int, statuses: Iterable[str], limit: int) -> list[str]:
        return list(self.session.scalars(
            select(ConversationTurn.question).join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(
                Conversation.user_id == user_id, Conversation.database_id == database_id,
                ConversationTurn.status.in_(list(statuses)),
            ).order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc()).limit(limit)
        ).all())

    def database_results(self, database_id: int, statuses: Iterable[str], limit: int) -> list[list | None]:
        return list(self.session.scalars(
            select(ConversationTurn.results).join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(Conversation.database_id == database_id, ConversationTurn.status.in_(list(statuses)))
            .order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc()).limit(limit)
        ).all())

    def feedback(self, turn_id: UUID, user_id: int) -> ConversationTurnFeedback | None:
        return self.session.scalar(select(ConversationTurnFeedback).where(
            ConversationTurnFeedback.turn_id == turn_id, ConversationTurnFeedback.user_id == user_id,
        ))

    def feedbacks(self, turn_ids: Iterable[UUID], user_id: int) -> dict[UUID, ConversationTurnFeedback]:
        ids = list(turn_ids)
        if not ids:
            return {}
        rows = self.session.scalars(select(ConversationTurnFeedback).where(
            ConversationTurnFeedback.turn_id.in_(ids), ConversationTurnFeedback.user_id == user_id,
        ))
        return {row.turn_id: row for row in rows}
