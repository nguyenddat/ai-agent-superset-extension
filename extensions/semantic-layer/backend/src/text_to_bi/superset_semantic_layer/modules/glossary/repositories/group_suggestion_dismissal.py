from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import GroupSuggestionDismissal


class GroupSuggestionDismissalRepository(BaseRepository[GroupSuggestionDismissal]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GroupSuggestionDismissal)

    def fingerprints(self, kind: str) -> set[str]:
        return {row.fingerprint for row in self.query().filter_by(kind=kind).all()}
