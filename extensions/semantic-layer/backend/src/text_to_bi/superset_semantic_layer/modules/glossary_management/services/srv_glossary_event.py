from datetime import datetime, timezone

from ..dependencies import glossary_event_repository
from ..models import GlossaryTermAuditEvent, GlossaryTermRevision
from .srv_glossary_validation import MAX_REASON_LENGTH


class GlossaryEventService:
    def __init__(self) -> None:
        self.events = glossary_event_repository()

    # -------------------------CREATE-------------------------
    def create(
        self, revision: GlossaryTermRevision, event_type: str, actor_id: int, reason: str | None = None
    ) -> None:
        """Ghi một sự kiện vào lịch sử thuật ngữ; sự kiện không bao giờ bị sửa."""
        values = {
            "term_id": revision.term_id,
            "revision_id": revision.id,
            "event_type": event_type,
            "actor_id": actor_id,
            "reason": reason[:MAX_REASON_LENGTH] if reason else reason,
            "revision_number": revision.revision_number,
            "occurred_at": datetime.now(timezone.utc),
        }
        self.events.create(values, flush=False)

    # -------------------------READ---------------------------
    def read_history(self, term_id: int) -> list[GlossaryTermAuditEvent]:
        return self.events.read_history(term_id)

    def read_author_id(self, revision: GlossaryTermRevision) -> int | None:
        """Người soạn một bản: người thực hiện sự kiện tạo hoặc sửa của bản đó."""
        event = self.events.read_latest_authoring(revision.id)
        return event.actor_id if event else None
