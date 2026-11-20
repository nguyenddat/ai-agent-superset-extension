from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository
from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus

from ..models.model_expert_rule import ExpertRuleRevision


class ExpertRuleRevisionRepository(BaseRepository[ExpertRuleRevision]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleRevision)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> ExpertRuleRevision:
        return self.add(ExpertRuleRevision(**values), flush=flush)

    # -------------------------READ---------------------------
    def read_current(self, rule_id: int) -> ExpertRuleRevision | None:
        return self.query().filter_by(rule_id=rule_id, is_current=True).one_or_none()

    def read_current_for_update(self, rule_id: int) -> ExpertRuleRevision | None:
        current = self.query().filter_by(rule_id=rule_id, is_current=True)
        return current.populate_existing().with_for_update().one_or_none()

    def read_all_current(self) -> list[ExpertRuleRevision]:
        return self.query().filter_by(is_current=True).order_by(ExpertRuleRevision.rule_id).all()

    def read_all(self) -> list[ExpertRuleRevision]:
        return self.query().order_by(ExpertRuleRevision.revision_number).all()

    def read_all_approved_current(self) -> list[ExpertRuleRevision]:
        return self.query().filter_by(status=ReviewStatus.APPROVED.value, is_current=True).all()
