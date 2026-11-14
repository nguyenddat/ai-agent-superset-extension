from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_expert_rule import ExpertRuleGroup


class ExpertRuleGroupRepository(BaseRepository[ExpertRuleGroup]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleGroup)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> ExpertRuleGroup:
        return self.add(ExpertRuleGroup(**values), flush=flush)

    # -------------------------READ---------------------------
    def read(self, group_id: int) -> ExpertRuleGroup | None:
        return self.get(group_id)

    def read_all(self) -> list[ExpertRuleGroup]:
        """Mọi nhóm, theo tên."""
        return self.query().order_by(ExpertRuleGroup.name).all()

    def read_by_normalized_name(self, normalized_name: str) -> ExpertRuleGroup | None:
        return self.query().filter_by(normalized_name=normalized_name).one_or_none()

    # -------------------------UPDATE-------------------------
    def update(self, group: ExpertRuleGroup, values: dict[str, Any]) -> ExpertRuleGroup:
        return super().update(group, values)

    # -------------------------DELETE-------------------------
    def delete(self, group: ExpertRuleGroup) -> None:
        super().delete(group)
