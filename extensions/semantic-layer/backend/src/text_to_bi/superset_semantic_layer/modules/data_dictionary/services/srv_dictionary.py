from typing import Any

from superset.connectors.sqla.models import SqlaTable

from text_to_bi.superset_semantic_layer.modules.business_model.dependencies import data_layer_repository
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import datasets_by_name, get_dataset, is_internal_dataset

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository
from ..exceptions import DataDictionaryValidationError, ReferencedColumnMissingError
from ..models import ColumnDictionary, DatasetDictionary
from .srv_column_semantics import checked_column_semantics
from .srv_grain import checked_temporal_kind, save_time_semantics
from .srv_pii import checked_pii_flag
from .srv_seeding import read_dictionary_snapshot, seed_dictionary
from .srv_transformation import checked_transformation, save_transformation

DICTIONARY_FIELDS = {
    "aggregations",
    "business_term",
    "contains_pii",
    "default_value",
    "description",
    "display_name",
    "format",
    "is_fk",
    "is_pk",
    "is_unique",
    "nullable",
    "referenced_column",
    "referenced_dataset_id",
    "referenced_column_name",
    "semantic_role",
    "synonyms",
    "temporal_kind",
    "transformation",
    "unit",
}

STRING_FIELD_LIMITS = {"display_name": 255}

OPTIONAL_STRING_FIELD_LIMITS = {"format": 128, "unit": 128}

DATASET_DICTIONARY_FIELDS = {"display_name", "description", "grain", "create_column", "dataset_type", "layer_id", "contains_pii"}

# Saved together: the grains are checked against the time column and the column telling kinds of rows apart.
DATASET_TIME_FIELDS = {"time_column", "row_kind_column", "grains"}


class DataDictionaryService:
    def __init__(self) -> None:
        self.datasets = dataset_dictionary_repository()
        self.columns = column_dictionary_repository()

    # -------------------------READ---------------------------
    def read(self, dataset: SqlaTable) -> tuple[DatasetDictionary, list[ColumnDictionary]]:
        """Đọc từ điển và mặc định cho các cột còn thiếu, không ghi database."""
        return read_dictionary_snapshot(dataset)

    def read_reference_options(self) -> list[dict[str, Any]]:
        """Dataset Superset và cột của chúng để chọn đích khóa ngoại, kèm cột khóa đã khai báo."""
        # Key flags declared in the data dictionary let the picker offer key columns as FK targets first.
        key_flags: dict[int, dict[str, dict[str, bool]]] = {}
        for row in self.columns.read_key_columns():
            key_flags.setdefault(row.dataset_id, {})[row.column_name] = {"pk": bool(row.is_pk), "unique": bool(row.is_unique)}
        options = []
        for dataset in datasets_by_name():
            if is_internal_dataset(dataset):
                continue
            database_name = getattr(dataset.database, "database_name", None)
            label = ".".join(part for part in (database_name, dataset.schema, dataset.table_name) if part)
            options.append(
                {
                    "id": dataset.id,
                    "dataset_name": dataset.table_name,
                    "label": label or dataset.table_name,
                    "database_name": database_name,
                    "schema": dataset.schema,
                    "columns": [str(column.column_name) for column in dataset.columns],
                    "column_types": {str(column.column_name): str(getattr(column, "type", None) or "")[:64] for column in dataset.columns},
                    "key_columns": key_flags.get(dataset.id, {}),
                }
            )
        return options

    # -------------------------UPDATE-------------------------
    def update(self, dataset: SqlaTable, payload: Any) -> tuple[DatasetDictionary, list[ColumnDictionary]]:
        """Lưu metadata của dataset và các cột gửi lên; trả từ điển như sau khi lưu. Người gọi commit."""
        actual_column_names = {str(column.column_name) for column in dataset.columns}
        updates = validate_dictionary_payload(payload, actual_column_names, dataset.id)
        dataset_updates, time_updates = normalize_dataset_payload(payload.get("dataset", {}), actual_column_names)

        # Seed first: each seed commits, so it must not run between the updates below and their commit.
        seed_dictionary(dataset)
        for referenced_id in {item["referenced_dataset_id"] for item in updates if item.get("referenced_dataset_id") is not None} - {dataset.id}:
            seed_dictionary(get_dataset(referenced_id))
        # A transformation's input columns need dictionary rows to point at.
        for source_dataset_id in {source_id for item in updates for source_id, _ in (item.get("transformation") or {}).get("sources", [])} - {dataset.id}:
            seed_dictionary(get_dataset(source_dataset_id))
        self.datasets.update(self.datasets.read(dataset.id), dataset_updates)
        rows_by_name = {row.column_name: row for row in self.columns.read_by_dataset(dataset.id)}
        for update in updates:
            self._update_column(rows_by_name[update.pop("column_name")], update)
        save_time_semantics(self.datasets.read(dataset.id), time_updates, rows_by_name)
        return self.datasets.read(dataset.id), self.columns.read_by_dataset(dataset.id)

    def _update_column(self, row: ColumnDictionary, update: dict[str, Any]) -> None:
        """Lưu một cột: phép biến đổi, khóa ngoại theo tên dataset và cột đích, rồi các trường còn lại."""
        if "transformation" in update:
            save_transformation(row.id, update.pop("transformation"))
        if "referenced_dataset_id" in update or "referenced_column_name" in update:
            referenced_dataset_id = update.pop("referenced_dataset_id", None)
            referenced_column_name = update.pop("referenced_column_name", None)
            if referenced_dataset_id is None or referenced_column_name is None:
                update["referenced_column"] = None
            else:
                referenced_row = self.columns.read_by_column_name(referenced_dataset_id, referenced_column_name)
                if referenced_row is None:
                    raise ReferencedColumnMissingError()
                update["referenced_column"] = referenced_row.id
        row = self.columns.update(row, update)
        if row.semantic_role != "measure" and row.aggregations:
            row.aggregations = None


def normalize_dataset_payload(dataset_updates: Any, actual_column_names: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Kiểm tra phần `dataset` của một lần lưu; trả (trường của dataset, trường thời gian lưu riêng)."""
    if not isinstance(dataset_updates, dict):
        raise DataDictionaryValidationError("dataset must be an object.")
    time_updates = {field: dataset_updates.pop(field) for field in DATASET_TIME_FIELDS if field in dataset_updates}
    for field in ("time_column", "row_kind_column"):
        if time_updates.get(field) == "":
            time_updates[field] = None
    unknown_fields = set(dataset_updates) - DATASET_DICTIONARY_FIELDS
    if unknown_fields:
        raise DataDictionaryValidationError(f"dataset contains unsupported fields: {', '.join(sorted(unknown_fields))}.")
    for field in ("display_name", "description", "grain", "create_column"):
        if field not in dataset_updates:
            continue
        value = dataset_updates.get(field)
        if field == "display_name":
            if not isinstance(value, str) or not value.strip() or len(value) > 255:
                raise DataDictionaryValidationError("dataset.display_name must be a non-empty string of at most 255 characters.")
        elif value is not None and not isinstance(value, str):
            raise DataDictionaryValidationError(f"dataset.{field} must be a string or null.")
    for field in ("description", "grain", "create_column"):
        value = dataset_updates.get(field)
        # A blank value means unset; a stored empty string would read back as a real value.
        if isinstance(value, str) and not value.strip():
            dataset_updates[field] = None
        elif field == "create_column" and isinstance(value, str):
            dataset_updates[field] = value.strip()
    if dataset_updates.get("dataset_type") not in (None, "base", "aggregate"):
        raise DataDictionaryValidationError("dataset.dataset_type must be 'base', 'aggregate', or null.")
    if dataset_updates.get("create_column") and dataset_updates["create_column"] not in actual_column_names:
        raise DataDictionaryValidationError("dataset.create_column must reference a column in this dataset.")
    layer_id = dataset_updates.get("layer_id")
    if layer_id is not None and (isinstance(layer_id, bool) or not isinstance(layer_id, int) or data_layer_repository().get(layer_id) is None):
        raise DataDictionaryValidationError("dataset.layer_id must reference an existing data layer or be null.")
    if "contains_pii" in dataset_updates:
        dataset_updates["contains_pii"] = checked_pii_flag(dataset_updates["contains_pii"], "dataset.contains_pii")
    return dataset_updates, time_updates


def validate_dictionary_payload(payload: Any, actual_column_names: set[str], dataset_id: int) -> list[dict[str, Any]]:
    """Kiểm tra mảng `columns` của một lần lưu; trả giá trị đã chuẩn hóa của từng cột."""
    if not isinstance(payload, dict) or not isinstance(payload.get("columns"), list):
        raise DataDictionaryValidationError("Request body must contain a columns array.")

    # Transformations name columns of other datasets; each is looked up once.
    dataset_columns: dict[int, set[str] | None] = {dataset_id: actual_column_names}

    def columns_of(source_dataset_id: int) -> set[str] | None:
        if source_dataset_id not in dataset_columns:
            source = get_dataset(source_dataset_id)
            dataset_columns[source_dataset_id] = None if source is None else {str(column.column_name) for column in source.columns}
        return dataset_columns[source_dataset_id]

    normalized: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, item in enumerate(payload["columns"]):
        if not isinstance(item, dict):
            raise DataDictionaryValidationError(f"columns[{index}] must be an object.")
        unknown_fields = set(item) - DICTIONARY_FIELDS - {"column_name"}
        if unknown_fields:
            raise DataDictionaryValidationError(f"columns[{index}] contains unsupported fields: {', '.join(sorted(unknown_fields))}.")
        column_name = item.get("column_name")
        if not isinstance(column_name, str) or not column_name:
            raise DataDictionaryValidationError(f"columns[{index}].column_name must be a non-empty string.")
        if column_name not in actual_column_names:
            raise DataDictionaryValidationError(f"Unknown dataset column: {column_name}.")
        if column_name in seen_names:
            raise DataDictionaryValidationError(f"Duplicate dataset column: {column_name}.")
        seen_names.add(column_name)

        values = {"column_name": column_name}
        for field, max_length in STRING_FIELD_LIMITS.items():
            if field not in item:
                continue
            value = item[field]
            if not isinstance(value, str) or not value.strip():
                raise DataDictionaryValidationError(f"columns[{index}].{field} must be a non-empty string.")
            if len(value) > max_length:
                raise DataDictionaryValidationError(f"columns[{index}].{field} must be at most {max_length} characters.")
            values[field] = value
        for field in ("default_value", "business_term"):
            if field in item:
                value = item[field]
                if value is not None and not isinstance(value, str):
                    raise DataDictionaryValidationError(f"columns[{index}].{field} must be a string or null.")
                if field == "business_term" and value is not None and not value.strip():
                    value = None
                values[field] = value
        for field in ("nullable", "is_pk", "is_fk", "is_unique"):
            if field in item:
                if not isinstance(item[field], bool):
                    raise DataDictionaryValidationError(f"columns[{index}].{field} must be a boolean.")
                values[field] = item[field]
        values.update(_checked_reference(item, index, column_name, actual_column_names, dataset_id))
        for field in ("unit", "format"):
            if field in item:
                value = item[field]
                if value is not None and (not isinstance(value, str) or len(value) > OPTIONAL_STRING_FIELD_LIMITS[field]):
                    raise DataDictionaryValidationError(f"columns[{index}].{field} must be a string of at most 128 characters or null.")
                values[field] = value if value is None or value.strip() else None
        if "temporal_kind" in item:
            values["temporal_kind"] = checked_temporal_kind(item["temporal_kind"], index)
        # The stored role is not known here; the save clears aggregations on a column that ends up not a measure.
        values.update(checked_column_semantics(item, index, item.get("semantic_role")))
        if "transformation" in item:
            values["transformation"] = checked_transformation(item["transformation"], f"columns[{index}].transformation", (dataset_id, column_name), columns_of)
        if "contains_pii" in item:
            values["contains_pii"] = checked_pii_flag(item["contains_pii"], f"columns[{index}].contains_pii")
        normalized.append(values)
    return normalized


def _checked_reference(item: dict[str, Any], index: int, column_name: str, actual_column_names: set[str], dataset_id: int) -> dict[str, Any]:
    """Khóa ngoại của một cột: theo ID dataset và tên cột đích, hoặc theo tên cột cùng dataset (dạng cũ)."""
    if "referenced_dataset_id" in item or "referenced_column_name" in item:
        referenced_dataset_id = item.get("referenced_dataset_id")
        referenced_column_name = item.get("referenced_column_name")
        if referenced_dataset_id is None and referenced_column_name is None:
            return {"referenced_dataset_id": None, "referenced_column_name": None}
        if (
            isinstance(referenced_dataset_id, bool)
            or not isinstance(referenced_dataset_id, int)
            or not isinstance(referenced_column_name, str)
            or not referenced_column_name
        ):
            raise DataDictionaryValidationError(f"columns[{index}] must specify both a referenced dataset and column.")
        referenced_dataset = get_dataset(referenced_dataset_id)
        if referenced_dataset is None:
            raise DataDictionaryValidationError(f"Unknown referenced dataset: {referenced_dataset_id}.")
        if referenced_column_name not in {str(column.column_name) for column in referenced_dataset.columns}:
            raise DataDictionaryValidationError(f"Unknown referenced column: {referenced_column_name}.")
        if referenced_dataset_id == dataset_id and referenced_column_name == column_name:
            raise DataDictionaryValidationError("A column cannot reference itself.")
        return {"referenced_dataset_id": referenced_dataset_id, "referenced_column_name": referenced_column_name}
    if "referenced_column" in item:
        referenced_column = item["referenced_column"]
        if referenced_column is not None and not isinstance(referenced_column, str):
            raise DataDictionaryValidationError(f"columns[{index}].referenced_column must be a column name or null.")
        if referenced_column == column_name:
            raise DataDictionaryValidationError("A column cannot reference itself.")
        if referenced_column is not None and referenced_column not in actual_column_names:
            raise DataDictionaryValidationError(f"Unknown referenced column: {referenced_column}.")
        return {"referenced_dataset_id": dataset_id if referenced_column else None, "referenced_column_name": referenced_column}
    return {}
