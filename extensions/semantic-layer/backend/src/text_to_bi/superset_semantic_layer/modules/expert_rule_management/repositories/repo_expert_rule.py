from typing import Any

from sqlalchemy.orm import Session, joinedload

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_expert_rule import ExpertRule


class ExpertRuleRepository(BaseRepository[ExpertRule]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRule)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> ExpertRule:
        return self.add(ExpertRule(**values), flush=flush)

    # -------------------------READ---------------------------
    def read_all(self) -> list[ExpertRule]:
        return self.query().options(joinedload(ExpertRule.group)).all()

    def read(self, rule_id: int) -> ExpertRule | None:
        return self.get(rule_id)

    def read_fresh(self, rule_id: int) -> ExpertRule | None:
        """Đọc bằng query thay vì identity map, để thấy đúng dòng vừa khóa."""
        return self.query().filter(ExpertRule.id == rule_id).one_or_none()

    def read_by_normalized_name(self, normalized_name: str) -> ExpertRule | None:
        return self.query().filter_by(normalized_name=normalized_name).one_or_none()

    def read_in_group(self, group_id: int) -> list[ExpertRule]:
        return self.query().filter_by(group_id=group_id).order_by(ExpertRule.id).all()

    def read_for_update(self, rule_id: int) -> ExpertRule | None:
        """Đọc lại rule và giữ khóa dòng tới hết transaction."""
        return self.query().filter(ExpertRule.id == rule_id).populate_existing().with_for_update().one_or_none()
