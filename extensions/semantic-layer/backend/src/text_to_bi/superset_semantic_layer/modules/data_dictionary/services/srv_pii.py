from collections.abc import Mapping
from typing import Any

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository
from ..exceptions import DataDictionaryValidationError


def checked_pii_flag(value: Any, field: str) -> bool:
    """Dấu PII gửi lên cho dataset hoặc cột, phải là true hoặc false."""
    if not isinstance(value, bool):
        raise DataDictionaryValidationError(f"{field} phải là true hoặc false.")
    return value


def mark_catalog_pii(
    catalog_datasets: list[dict[str, Any]], dataset_flags: Mapping[int, bool], column_flags: Mapping[tuple[int, str], bool]
) -> None:
    """Thêm `contains_pii` cho mỗi dataset và dimension của catalog."""
    for dataset in catalog_datasets:
        dataset["contains_pii"] = bool(dataset_flags.get(dataset["id"], False))
        for dimension in dataset.get("dimensions", []):
            dimension["contains_pii"] = bool(column_flags.get((dataset["id"], dimension["name"]), False))


def label_catalog_pii(catalog_datasets: list[dict[str, Any]]) -> None:
    """Gắn dấu PII mà Data Dictionary đặt cho từng dataset và dimension của catalog, để bên tiêu thụ thấy."""
    dataset_ids = [dataset["id"] for dataset in catalog_datasets]
    if not dataset_ids:
        return
    dataset_flags = dataset_dictionary_repository().read_pii_flags(dataset_ids)
    column_flags = {
        (entry.dataset_id, entry.column_name): bool(entry.contains_pii) for entry in column_dictionary_repository().read_by_datasets(dataset_ids)
    }
    mark_catalog_pii(catalog_datasets, dataset_flags, column_flags)
