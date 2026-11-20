from datetime import datetime, timezone

from ..dependencies import expert_rule_event_repository
from ..models import ExpertRuleAuditEvent, ExpertRuleRevision
from .srv_expert_rule_validation import MAX_REASON


class ExpertRuleEventService:
    def __init__(self) -> None:
        self.events = expert_rule_event_repository()

    # -------------------------CREATE-------------------------
    def create(self, revision: ExpertRuleRevision, event_type: str, actor_id: int, reason: str | None = None) -> None:
        values = {
            "rule_id": revision.rule_id,
            "revision_id": revision.id,
            "event_type": event_type,
            "actor_id": actor_id,
            "reason": reason[:MAX_REASON] if reason else reason,
            "revision_number": revision.revision_number,
            "lifecycle_version": revision.lifecycle_version,
            "occurred_at": datetime.now(timezone.utc),
        }
        self.events.create(values, flush=False)

    # -------------------------READ---------------------------
    def read_history(self, rule_id: int) -> list[ExpertRuleAuditEvent]:
        return self.events.read_history(rule_id)

    def read_author_id(self, revision: ExpertRuleRevision) -> int | None:
        event = self.events.read_latest_authoring(revision.id)
        return event.actor_id if event else None
