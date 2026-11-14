from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository

from ..models import DatasetGrain


class DatasetGrainRepository(BaseRepository[DatasetGrain]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DatasetGrain)

    # -------------------------READ---------------------------
    def read_by_dataset(self, dataset_id: int) -> list[DatasetGrain]:
        return self.query().filter(DatasetGrain.dataset_id == dataset_id).all()

    def read_by_datasets(self, dataset_ids: Iterable[int]) -> list[DatasetGrain]:
        return self.query().filter(DatasetGrain.dataset_id.in_(list(dataset_ids))).all()

    def read_by_row_kind(self, dataset_id: int) -> list[DatasetGrain]:
        """Grain của dataset, sắp theo giá trị loại dòng."""
        return self.query().filter(DatasetGrain.dataset_id == dataset_id).order_by(DatasetGrain.row_kind_value).all()

    # -------------------------UPDATE-------------------------
    def update_dataset_grains(self, stored: Iterable[DatasetGrain], dataset_id: int, grains: Iterable[dict[str, Any]]) -> None:
        """Thay toàn bộ grain của một dataset bằng danh sách mới."""
        for item in stored:
            self.delete(item)
        # The unique row kind constraint must see the old rows gone before the new ones arrive.
        self.flush()
        self.add_all(DatasetGrain(dataset_id=dataset_id, **item) for item in grains)
        self.flush()
