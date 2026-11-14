from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_glossary import GlossaryTermGroup


class GlossaryGroupRepository(BaseRepository[GlossaryTermGroup]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GlossaryTermGroup)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> GlossaryTermGroup:
        return self.add(GlossaryTermGroup(**values), flush=flush)

    # -------------------------READ---------------------------
    def read(self, group_id: int) -> GlossaryTermGroup | None:
        return self.get(group_id)

    def read_all(self) -> list[GlossaryTermGroup]:
        """Mọi nhóm, theo tên."""
        return self.query().order_by(GlossaryTermGroup.name).all()

    def read_by_normalized_name(self, normalized_name: str) -> GlossaryTermGroup | None:
        return self.query().filter_by(normalized_name=normalized_name).one_or_none()

    # -------------------------UPDATE-------------------------
    def update(self, group: GlossaryTermGroup, values: dict[str, Any]) -> GlossaryTermGroup:
        return super().update(group, values)

    # -------------------------DELETE-------------------------
    def delete(self, group: GlossaryTermGroup) -> None:
        super().delete(group)
