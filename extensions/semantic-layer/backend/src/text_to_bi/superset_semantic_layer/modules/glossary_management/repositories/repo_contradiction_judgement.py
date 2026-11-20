from collections.abc import Collection
from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_contradiction import ContradictionJudgement


class ContradictionJudgementRepository(BaseRepository[ContradictionJudgement]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ContradictionJudgement)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> ContradictionJudgement:
        return self.add(ContradictionJudgement(**values), flush=flush)

    # -------------------------READ---------------------------
    def read_by_fingerprints(self, fingerprints: Collection[str]) -> list[ContradictionJudgement]:
        return self.query().filter(ContradictionJudgement.fingerprint.in_(list(fingerprints))).all()

    # -------------------------DELETE-------------------------
    def delete_except(self, fingerprints: Collection[str]) -> None:
        stale = self.query().filter(ContradictionJudgement.fingerprint.notin_(list(fingerprints)))
        stale.delete(synchronize_session=False)
