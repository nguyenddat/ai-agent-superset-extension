from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_contradiction import Contradiction


class ContradictionRepository(BaseRepository[Contradiction]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Contradiction)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> Contradiction:
        return self.add(Contradiction(**values), flush=flush)

    # -------------------------READ---------------------------
    def read(self, contradiction_id: int) -> Contradiction | None:
        return self.get(contradiction_id)

    def read_all(self) -> list[Contradiction]:
        return self.query().order_by(Contradiction.id).all()

    # -------------------------DELETE-------------------------
    def delete(self, contradiction: Contradiction) -> None:
        super().delete(contradiction)
