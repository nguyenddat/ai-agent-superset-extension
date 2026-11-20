from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository
from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus

from ..models.model_glossary import GlossaryTermRevision

# A reviewer decided these revisions; a draft is still waiting.
DECIDED = (ReviewStatus.APPROVED.value, ReviewStatus.REVOKED.value)


class GlossaryRevisionRepository(BaseRepository[GlossaryTermRevision]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTermRevision)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> GlossaryTermRevision:
        return self.add(GlossaryTermRevision(**values), flush=flush)

    # -------------------------READ---------------------------
    def read(self, revision_id: int) -> GlossaryTermRevision | None:
        return self.get(revision_id)

    def read_current(self, term_id: int) -> GlossaryTermRevision | None:
        return self.query().filter_by(term_id=term_id, is_current=True).one_or_none()

    def read_current_for_update(self, term_id: int) -> GlossaryTermRevision | None:
        current = self.query().filter_by(term_id=term_id, is_current=True)
        return current.populate_existing().with_for_update().one_or_none()

    def read_by_term(self, term_id: int) -> list[GlossaryTermRevision]:
        return self.query().filter_by(term_id=term_id).order_by(GlossaryTermRevision.revision_number).all()

    def read_serving(self, term_id: int) -> GlossaryTermRevision | None:
        decided = (
            self.query()
            .filter(GlossaryTermRevision.term_id == term_id, GlossaryTermRevision.status.in_(DECIDED))
            .order_by(GlossaryTermRevision.revision_number.desc())
            .first()
        )
        return decided if decided is not None and decided.status == ReviewStatus.APPROVED else None

    def read_all_serving(self) -> list[GlossaryTermRevision]:
        decided = (
            self.query()
            .filter(GlossaryTermRevision.status.in_(DECIDED))
            .order_by(GlossaryTermRevision.term_id, GlossaryTermRevision.revision_number)
            .all()
        )
        latest = {revision.term_id: revision for revision in decided}
        return [revision for revision in latest.values() if revision.status == ReviewStatus.APPROVED]
