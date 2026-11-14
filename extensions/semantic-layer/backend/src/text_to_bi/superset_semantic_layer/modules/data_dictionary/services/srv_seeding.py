from typing import Any

from sqlalchemy.exc import IntegrityError
from superset import db
from superset.connectors.sqla.models import SqlaTable

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository
from ..models import ColumnDictionary, DatasetDictionary
from ..repositories.repo_column_dictionary import ColumnDictionaryRepository
from ..repositories.repo_dataset_dictionary import DatasetDictionaryRepository
from .srv_column_semantics import default_semantic_role
from .srv_grain import default_temporal_kind


def seed_dictionary(dataset: SqlaTable) -> None:
    """Đồng bộ dòng từ điển của dataset với cột Superset rồi commit.

    Commit ở đây để không để transaction mở cho phần sau. Hai request cùng seed một dataset mới va nhau ở khóa unique;
    bên thua rollback và thử lại, khi đó thấy các dòng bên thắng đã tạo.
    """
    for attempt in range(2):
        try:
            _read_or_create_dataset_dictionary(dataset, dataset_dictionary_repository())
            _seed_dictionary_columns(dataset, column_dictionary_repository())
            db.session.commit()
            return
        except IntegrityError:
            db.session.rollback()
            if attempt:
                raise


def _column_metadata_values(column: Any) -> dict[str, Any]:
    column_name = str(column.column_name)
    temporal_kind = default_temporal_kind(getattr(column, "type", None), bool(getattr(column, "is_dttm", False)))
    return {
        "column_name": column_name,
        "display_name": str(getattr(column, "verbose_name", None) or column_name)[:255],
        "data_type": str(getattr(column, "type", None) or "UNKNOWN")[:128],
        "nullable": bool(getattr(column, "nullable", True)),
        "default_value": None,
        "is_pk": False,
        "is_fk": False,
        "referenced_column": None,
        "is_unique": False,
        "unit": None,
        "format": None,
        "business_term": None,
        "temporal_kind": temporal_kind,
        "semantic_role": default_semantic_role(getattr(column, "type", None), temporal_kind, is_key=False),
    }


def _seed_dictionary_columns(dataset: SqlaTable, repository: ColumnDictionaryRepository) -> list[ColumnDictionary]:
    existing = {column.column_name: column for column in repository.read_by_dataset(dataset.id)}
    actual_names = {str(column.column_name) for column in dataset.columns}
    # Columns dropped or renamed in Superset leave dictionary rows behind; references to them are cleared by the FK.
    for stale_name in [name for name in existing if name not in actual_names]:
        repository.delete(existing.pop(stale_name))
    for actual_column in dataset.columns:
        column_name = str(actual_column.column_name)
        if column_name not in existing:
            existing[column_name] = repository.create({"dataset_id": dataset.id, **_column_metadata_values(actual_column)})
    return list(existing.values())


def _read_or_create_dataset_dictionary(dataset: SqlaTable, repository: DatasetDictionaryRepository) -> DatasetDictionary:
    record = repository.read(dataset.id)
    if record is None:
        record = repository.create(
            {"id": dataset.id, "dataset_name": dataset.table_name, "display_name": dataset.table_name, "description": dataset.description}
        )
    return record


def read_dictionary_snapshot(dataset: SqlaTable) -> tuple[DatasetDictionary, list[ColumnDictionary]]:
    """Đọc metadata đã lưu; dòng còn thiếu là object tạm không thêm vào session, không flush hay commit."""
    record = dataset_dictionary_repository().read(dataset.id)
    if record is None:
        record = DatasetDictionary(id=dataset.id, dataset_name=dataset.table_name, display_name=dataset.table_name, description=dataset.description, contains_pii=False)
    stored = {column.column_name: column for column in column_dictionary_repository().read_by_dataset(dataset.id)}
    columns = [stored.get(str(column.column_name)) or ColumnDictionary(dataset_id=dataset.id, contains_pii=False, **_column_metadata_values(column)) for column in dataset.columns]
    return record, columns
