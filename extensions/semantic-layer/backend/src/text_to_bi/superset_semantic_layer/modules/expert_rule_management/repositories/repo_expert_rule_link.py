from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_expert_rule import ExpertRuleLink


class ExpertRuleLinkRepository(BaseRepository[ExpertRuleLink]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleLink)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> ExpertRuleLink:
        return self.add(ExpertRuleLink(**values), flush=flush)

    # -------------------------READ---------------------------
    def read_for_revisions(self, revision_ids: list[int]) -> dict[int, list[ExpertRuleLink]]:
        result: dict[int, list[ExpertRuleLink]] = {}
        for link in self.query().filter(ExpertRuleLink.revision_id.in_(revision_ids)).order_by(ExpertRuleLink.id).all():
            result.setdefault(link.revision_id, []).append(link)
        return result

    def read_by_revision(self, revision_id: int) -> list[ExpertRuleLink]:
        return self.query().filter_by(revision_id=revision_id).order_by(ExpertRuleLink.id).all()
