from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import Contradiction


class ContradictionRepository(BaseRepository[Contradiction]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Contradiction)

    def by_id(self) -> list[Contradiction]:
        return self.query().order_by(Contradiction.id).all()
