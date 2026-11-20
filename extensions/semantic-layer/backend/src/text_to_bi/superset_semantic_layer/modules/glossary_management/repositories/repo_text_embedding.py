from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models.model_grouping import TextEmbedding


class TextEmbeddingRepository(BaseRepository[TextEmbedding]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, TextEmbedding)

    # -------------------------CREATE-------------------------
    def create(self, values: dict[str, Any], *, flush: bool = True) -> TextEmbedding:
        return self.add(TextEmbedding(**values), flush=flush)

    # -------------------------READ---------------------------
    def read_vectors(self, model: str, content_hashes: list[str]) -> dict[str, list[float]]:
        if not content_hashes:
            return {}
        rows = self.query().filter(TextEmbedding.model == model, TextEmbedding.content_hash.in_(content_hashes)).all()
        return {row.content_hash: row.vector for row in rows}
