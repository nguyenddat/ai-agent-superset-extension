from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_glossary import GlossaryTermAuditEvent


class GlossaryEventRepository(BaseRepository[GlossaryTermAuditEvent]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTermAuditEvent)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> GlossaryTermAuditEvent:
        return self.add(GlossaryTermAuditEvent(**values), flush=flush)

    # -------------------------READ---------------------------
    def read_history(self, term_id: int) -> list[GlossaryTermAuditEvent]:
        return self.query().filter_by(term_id=term_id).order_by(GlossaryTermAuditEvent.id).all()

    def read_latest_authoring(self, revision_id: int) -> GlossaryTermAuditEvent | None:
        """Sự kiện tạo hoặc sửa gần nhất của một bản; người thực hiện là tác giả."""
        return (
            self.query()
            .filter(GlossaryTermAuditEvent.revision_id == revision_id)
            .filter(GlossaryTermAuditEvent.event_type.in_(("created", "updated")))
            .order_by(GlossaryTermAuditEvent.id.desc())
            .first()
        )
