from collections.abc import Callable, Iterable
from typing import Any

from ..dependencies import column_dictionary_repository, column_transformation_repository
from ..exceptions import DataDictionaryValidationError, TransformationSourceMissingError

TRANSFORMATION_MAX_SOURCES = 20

TRANSFORMATION_EXPRESSION_LIMIT = 4000


def checked_transformation(value: Any, field: str, target: tuple[int, str], columns_of: Callable[[int], set[str] | None]) -> dict[str, Any] | None:
    """Phép biến đổi của một cột gửi từ Data Dictionary: các cột đầu vào và biểu thức tự do.

    `target` là (ID dataset, tên cột) đang mô tả; `columns_of` trả tên cột hiện có của một dataset, None nếu không
    có dataset. Biểu thức giữ nguyên, không phân tích; trả None để bỏ phép biến đổi.
    """
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"expression", "sources"}:
        raise DataDictionaryValidationError(f"{field} phải là object gồm expression và sources, hoặc null.")
    expression = value.get("expression")
    if expression is not None and not isinstance(expression, str):
        raise DataDictionaryValidationError(f"{field}.expression phải là chuỗi hoặc null.")
    expression = (expression or "").strip()
    if len(expression) > TRANSFORMATION_EXPRESSION_LIMIT:
        raise DataDictionaryValidationError(f"{field}.expression dài tối đa {TRANSFORMATION_EXPRESSION_LIMIT} ký tự.")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise DataDictionaryValidationError(f"{field} cần ít nhất một cột nguồn.")
    if len(sources) > TRANSFORMATION_MAX_SOURCES:
        raise DataDictionaryValidationError(f"{field} có tối đa {TRANSFORMATION_MAX_SOURCES} cột nguồn.")
    checked: list[tuple[int, str]] = []
    for position, source in enumerate(sources):
        dataset_id = source.get("dataset_id") if isinstance(source, dict) else None
        column_name = source.get("column_name") if isinstance(source, dict) else None
        if isinstance(dataset_id, bool) or not isinstance(dataset_id, int) or not isinstance(column_name, str):
            raise DataDictionaryValidationError(f"{field}.sources[{position}] cần dataset_id và column_name.")
        if (dataset_id, column_name) == target:
            raise DataDictionaryValidationError("Một cột không thể là nguồn biến đổi của chính nó.")
        columns = columns_of(dataset_id)
        if columns is None:
            raise DataDictionaryValidationError(f"Không tìm thấy dataset nguồn {dataset_id}.")
        if column_name not in columns:
            raise DataDictionaryValidationError(f"Không tìm thấy cột nguồn {column_name} trong dataset {dataset_id}.")
        if (dataset_id, column_name) not in checked:
            checked.append((dataset_id, column_name))
    return {"expression": expression or None, "sources": checked}


def stored_transformations(column_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Phép biến đổi đã khai báo của các cột từ điển này, như Data Dictionary hiển thị."""
    repository = column_transformation_repository()
    transformations = {row.column_id: {"expression": row.expression, "sources": []} for row in repository.read_by_columns(column_ids)}
    for link, source in repository.read_sources(transformations):
        transformations[link.column_id]["sources"].append({"dataset_id": source.dataset_id, "column_name": source.column_name})
    return transformations


def save_transformation(column_id: int, value: dict[str, Any] | None) -> None:
    """Lưu phép biến đổi đã kiểm tra lên một cột từ điển, hoặc xóa nó khi `value` là None.

    Phép biến đổi không đổi thì giữ nguyên. Cột đầu vào chưa có dòng từ điển thì ném TransformationSourceMissingError;
    người gọi seed các dataset nguồn trước.
    """
    repository = column_transformation_repository()
    stored = repository.read(column_id)
    if value is None:
        if stored is not None:
            repository.update_sources(column_id, [])
            repository.delete(stored)
        return
    column_repository = column_dictionary_repository()
    source_ids = []
    for dataset_id, column_name in value["sources"]:
        source = column_repository.read_by_column_name(dataset_id, column_name)
        if source is None:
            raise TransformationSourceMissingError()
        source_ids.append(source.id)
    if stored is not None:
        current = [link.source_column_id for link, _ in repository.read_sources([column_id])]
        if stored.expression == value["expression"] and current == source_ids:
            return
    else:
        stored = repository.create(column_id)
    stored.expression = value["expression"]
    repository.update_sources(column_id, source_ids)
