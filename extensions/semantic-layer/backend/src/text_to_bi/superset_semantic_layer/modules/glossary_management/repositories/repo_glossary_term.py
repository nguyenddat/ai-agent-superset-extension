from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_glossary import GlossaryTerm


class GlossaryTermRepository(BaseRepository[GlossaryTerm]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTerm)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> GlossaryTerm:
        return self.add(GlossaryTerm(**values), flush=flush)

    # -------------------------READ---------------------------
    def read(self, term_id: int) -> GlossaryTerm | None:
        return self.get(term_id)

    def read_all(self) -> list[GlossaryTerm]:
        """Mọi thuật ngữ, theo tên."""
        return self.query().order_by(GlossaryTerm.canonical_name).all()

    def read_by_normalized_name(self, normalized_name: str) -> GlossaryTerm | None:
        return self.query().filter_by(normalized_name=normalized_name).one_or_none()

    def read_in_group(self, group_id: int) -> list[GlossaryTerm]:
        return self.query().filter_by(group_id=group_id).order_by(GlossaryTerm.id).all()

    def read_for_update(self, term_id: int) -> GlossaryTerm | None:
        """Đọc lại thuật ngữ và giữ khóa dòng tới hết transaction."""
        return self.query().filter(GlossaryTerm.id == term_id).populate_existing().with_for_update().one_or_none()
