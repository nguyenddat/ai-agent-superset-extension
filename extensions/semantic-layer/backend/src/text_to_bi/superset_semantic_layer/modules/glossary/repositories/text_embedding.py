from sqlalchemy.orm import Session

from ....common.base_repo import BaseRepository
from ..models import TextEmbedding


class TextEmbeddingRepository(BaseRepository[TextEmbedding]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, TextEmbedding)

    def vectors_for(self, model: str, content_hashes: list[str]) -> dict[str, list[float]]:
        """The model's cached vectors for those of the hashes it has, by hash."""
        if not content_hashes:
            return {}
        rows = self.query().filter(TextEmbedding.model == model, TextEmbedding.content_hash.in_(content_hashes)).all()
        return {row.content_hash: row.vector for row in rows}
