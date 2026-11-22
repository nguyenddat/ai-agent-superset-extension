# pyright: reportAbstractUsage=false

import json
from collections.abc import Iterable
from typing import Any

from superset.exceptions import SupersetSecurityException
from superset.extensions import security_manager
from superset_core.common import daos

from ..exceptions import DatasetNotFoundError

# Databases whose `extra` carries this flag hold the extension's own reporting views, not business data.
INTERNAL_DATABASE_FLAG = "text_to_bi_internal"


# -------------------------READ---------------------------
# Superset's DatasetDAO applies its datasource filter, so a dataset the caller cannot see is also not found.
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


def is_internal_dataset(dataset: Any) -> bool:
    try:
        extra = json.loads(getattr(getattr(dataset, "database", None), "extra", None) or "{}")
    except (TypeError, ValueError):
        return False
    return isinstance(extra, dict) and extra.get(INTERNAL_DATABASE_FLAG) is True


def can_access_dataset(dataset: Any) -> bool:
    try:
        security_manager.raise_for_access(datasource=dataset)
    except SupersetSecurityException:
        return False
    return True


def dataset_sort_key(dataset: Any) -> tuple[str, str, str, int]:
    return (database_name(dataset), dataset.schema or "", dataset.table_name or "", dataset.id)


# Business datasets the caller may read, ordered by database, schema and table name.
def readable_datasets() -> list[Any]:
    datasets = [
        dataset for dataset in daos.DatasetDAO.find_all()
        if not is_internal_dataset(dataset) and can_access_dataset(dataset)
    ]
    return sorted(datasets, key=dataset_sort_key)


def database_name(dataset: Any) -> str:
    return getattr(getattr(dataset, "database", None), "database_name", None) or ""


def dataset_kind(dataset: Any) -> str:
    return "virtual" if getattr(dataset, "sql", None) else "physical"


def dataset_columns(dataset: Any) -> list[Any]:
    return list(dataset.columns or [])


def column_type(column: Any) -> str:
    return str(getattr(column, "type", None) or "")
