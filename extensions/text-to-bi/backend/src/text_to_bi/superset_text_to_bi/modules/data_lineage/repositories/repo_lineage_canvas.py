from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import LineageCanvas


class LineageCanvasRepository(BaseRepository[LineageCanvas]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, LineageCanvas)

    # -------------------------READ---------------------------
    def read_for_database(self, database_id: int) -> LineageCanvas | None:
        return self.session.scalar(select(self.model).where(self.model.database_id == database_id))
