from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import AgentQuestion, AgentQuestionHandling


class AgentQuestionRepository(BaseRepository[AgentQuestion]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AgentQuestion)

    def in_session(self, session_id: int) -> list[AgentQuestion]:
        return self.query().filter(AgentQuestion.session_id == session_id).order_by(AgentQuestion.id).all()

    def one_in_session(self, question_id: int, session_id: int) -> AgentQuestion | None:
        return self.query().filter_by(id=question_id, session_id=session_id).one_or_none()

    def answered_in_session(
        self, session_id: int, excluded_question_id: int | None, limit: int,
    ) -> list[tuple[str, str]]:
        return (
            self.session.query(AgentQuestion.question, AgentQuestion.answer)
            .filter(AgentQuestion.session_id == session_id, AgentQuestion.id != (excluded_question_id or 0))
            .filter(AgentQuestion.answer.isnot(None), AgentQuestion.error.is_(None))
            .order_by(AgentQuestion.id.desc())
            .limit(limit)
            .all()
        )

    def detach_session(self, session_id: int) -> None:
        self.query().filter(AgentQuestion.session_id == session_id).update({AgentQuestion.session_id: None})

    def needs_review(self) -> list[tuple[AgentQuestion, AgentQuestionHandling | None]]:
        return (
            self.session.query(AgentQuestion, AgentQuestionHandling)
            .outerjoin(AgentQuestionHandling, AgentQuestionHandling.question_id == AgentQuestion.id)
            .filter(AgentQuestion.status == "needs_review")
            .order_by(AgentQuestion.created_on.desc())
            .all()
        )

    def texts(self, question_ids: set[int]) -> dict[int, str]:
        if not question_ids:
            return {}
        rows = self.session.query(AgentQuestion.id, AgentQuestion.question, AgentQuestion.rewritten_question).filter(
            AgentQuestion.id.in_(question_ids)
        )
        return {question_id: rewritten or question for question_id, question, rewritten in rows}


class AgentQuestionHandlingRepository(BaseRepository[AgentQuestionHandling]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AgentQuestionHandling)
