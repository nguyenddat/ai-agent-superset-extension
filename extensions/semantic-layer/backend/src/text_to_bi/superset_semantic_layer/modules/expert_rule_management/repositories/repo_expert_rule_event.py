from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_expert_rule import ExpertRuleAuditEvent


class ExpertRuleEventRepository(BaseRepository[ExpertRuleAuditEvent]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExpertRuleAuditEvent)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> ExpertRuleAuditEvent:
        return self.add(ExpertRuleAuditEvent(**values), flush=flush)

    # -------------------------READ---------------------------
    def read_history(self, rule_id: int) -> list[ExpertRuleAuditEvent]:
        return self.query().filter_by(rule_id=rule_id).order_by(ExpertRuleAuditEvent.id).all()

    def read_latest_authoring(self, revision_id: int) -> ExpertRuleAuditEvent | None:
        return (
            self.query()
            .filter(
                ExpertRuleAuditEvent.revision_id == revision_id,
                ExpertRuleAuditEvent.event_type.in_(("created", "updated")),
            )
            .order_by(ExpertRuleAuditEvent.id.desc())
            .first()
        )
