# pyright: reportAbstractUsage=false

import json
from collections.abc import Iterable
from typing import Any

from superset_core.common import daos

from ..exceptions import DatabaseNotFoundError, DatasetNotFoundError

INTERNAL_DATABASE_FLAG = "text_to_bi_internal"

def get_dataset(dataset_id: int) -> Any | None:
    return daos.DatasetDAO.find_one_or_none(id=dataset_id)

def require_dataset(dataset_id: int) -> Any:
    dataset = get_dataset(dataset_id)
    if dataset is None:
        raise DatasetNotFoundError()
    return dataset

def get_datasets(dataset_ids: Iterable[int]) -> list[Any]:
    wanted = set(dataset_ids)
    if not wanted:
        return []
    return [dataset for dataset in daos.DatasetDAO.find_all() if dataset.id in wanted]

def datasets_by_name() -> list[Any]:
    return sorted(daos.DatasetDAO.find_all(), key=lambda dataset: (dataset.table_name or "", dataset.id))

def datasets_on_database(database_id: int) -> list[Any]:
    datasets = daos.DatasetDAO.filter_by(database_id=database_id)
    return sorted(datasets, key=lambda dataset: (dataset.table_name or "", dataset.id))

def is_internal_dataset(dataset: Any) -> bool:
    database = getattr(dataset, "database", None)
    try:
        extra = json.loads(getattr(database, "extra", None) or "{}")
    except (TypeError, ValueError):
        return False
    return isinstance(extra, dict) and extra.get(INTERNAL_DATABASE_FLAG) is True

def business_datasets_by_name() -> dict[str, list[Any]]:
    datasets: dict[str, list[Any]] = {}
    for dataset in datasets_by_name():
        if not is_internal_dataset(dataset):
            datasets.setdefault(dataset.table_name, []).append(dataset)
    return datasets

def get_database(database_id: int) -> Any | None:
    return daos.DatabaseDAO.find_one_or_none(id=database_id)

def require_database(database_id: int) -> Any:
    database = get_database(database_id)
    if database is None:
        raise DatabaseNotFoundError()
    return database

def connection_identity(database: Any) -> dict[str, Any]:
    """Định danh kết nối của database cho mã băm hợp đồng, không chứa thông tin đăng nhập."""
    return {
        "id": getattr(database, "id", None),
        "name": getattr(database, "database_name", None),
        "uuid": getattr(database, "uuid", None),
        "backend": getattr(database, "backend", None),
    }


def dataset_for_creation_key(creation_key: str) -> Any | None:
    for dataset in daos.DatasetDAO.find_all():
        try:
            extra = json.loads(dataset.extra or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(extra, dict) and extra.get("text_to_bi_creation_key") == creation_key:
            return dataset
    return None
