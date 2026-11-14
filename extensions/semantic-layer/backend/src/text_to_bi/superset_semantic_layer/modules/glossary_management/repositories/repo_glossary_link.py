from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_glossary import GlossaryTermLink


class GlossaryLinkRepository(BaseRepository[GlossaryTermLink]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTermLink)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> GlossaryTermLink:
        return self.add(GlossaryTermLink(**values), flush=flush)

    # -------------------------READ---------------------------
    def read_by_revision(self, revision_id: int) -> list[GlossaryTermLink]:
        """Liên kết của một bản, theo thứ tự đã lưu."""
        return self.query().filter_by(revision_id=revision_id).order_by(GlossaryTermLink.id).all()

    def read_by_revision_dataset(self, revision_id: int, dataset_id: int) -> list[GlossaryTermLink]:
        return self.query().filter_by(revision_id=revision_id, dataset_id=dataset_id).all()
