from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_grouping import GroupSuggestionDismissal


class GroupSuggestionDismissalRepository(BaseRepository[GroupSuggestionDismissal]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GroupSuggestionDismissal)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> GroupSuggestionDismissal:
        try:
            with self.session.begin_nested():
                return self.add(GroupSuggestionDismissal(**values))
        except IntegrityError:
            existing = self.query().filter_by(kind=values["kind"], fingerprint=values["fingerprint"]).one_or_none()
            if existing is None:
                raise
            return existing

    # -------------------------READ---------------------------
    def read_fingerprints(self, kind: str) -> set[str]:
        return {row.fingerprint for row in self.query().filter_by(kind=kind).all()}
