from collections.abc import Collection

from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import ContradictionJudgement


class ContradictionJudgementRepository(BaseRepository[ContradictionJudgement]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ContradictionJudgement)

    def for_fingerprints(self, fingerprints: Collection[str]) -> list[ContradictionJudgement]:
        return self.query().filter(ContradictionJudgement.fingerprint.in_(list(fingerprints))).all()

    def delete_except(self, fingerprints: Collection[str]) -> None:
        """Forget the verdicts on content no check reads any more."""
        stale = self.query().filter(ContradictionJudgement.fingerprint.notin_(list(fingerprints)))
        stale.delete(synchronize_session=False)
