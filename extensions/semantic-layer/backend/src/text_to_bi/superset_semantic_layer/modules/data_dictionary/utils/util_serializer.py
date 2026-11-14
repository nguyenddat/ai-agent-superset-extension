from typing import Any

from superset.connectors.sqla.models import SqlaTable

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import iso_datetime, json_list
from text_to_bi.superset_semantic_layer.core.security import is_admin
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_datasets

from ..dependencies import column_dictionary_repository, dataset_grain_repository
from ..models import ColumnDictionary, DatasetDictionary, RelationshipContract
from ..services.srv_relationship_contract import RelationshipEnd, relationship_is_approved_current
from ..services.srv_relationship_discovery import current_verification
from ..services.srv_relationship_lookup import relationship_ends
from ..services.srv_transformation import stored_transformations


# -------------------------DICTIONARY---------------------
def serialize_dictionary(dataset: SqlaTable, dictionary: DatasetDictionary, columns: list[ColumnDictionary]) -> dict[str, Any]:
    """Từ điển của dataset, cột theo đúng thứ tự cột Superset, kèm khóa ngoại, grain và phép biến đổi."""
    records = {column.column_name: column for column in columns}
    # One query per kind of record, not one per referenced column.
    referenced_ids = {row.referenced_column for row in columns if row.referenced_column is not None}
    references_by_id = {row.id: row for row in column_dictionary_repository().read_by_ids(referenced_ids)} if referenced_ids else {}
    referenced_dataset_ids = {row.dataset_id for row in references_by_id.values()}
    datasets_by_id = {row.id: row for row in get_datasets(referenced_dataset_ids)}

    def reference_values(row: ColumnDictionary) -> dict[str, Any]:
        referenced = references_by_id.get(row.referenced_column)
        referenced_dataset = datasets_by_id.get(referenced.dataset_id) if referenced else None
        database_name = getattr(getattr(referenced_dataset, "database", None), "database_name", None)
        schema_name = getattr(referenced_dataset, "schema", None) if referenced_dataset else None
        table_name = getattr(referenced_dataset, "table_name", None) if referenced_dataset else None
        label = ".".join(part for part in (database_name, schema_name, table_name) if part)
        return {
            "referenced_column": referenced.column_name if referenced else None,
            "referenced_dataset_id": referenced.dataset_id if referenced else None,
            "referenced_column_name": referenced.column_name if referenced else None,
            "referenced_dataset_label": label or (table_name if referenced else None),
        }

    grains = dataset_grain_repository().read_by_row_kind(dataset.id)
    transformations = stored_transformations(row.id for row in columns if row.id is not None)

    def column_values(actual: Any) -> dict[str, Any]:
        record = records[actual.column_name]
        return {
            "id": record.id,
            "column_name": actual.column_name,
            "display_name": record.display_name,
            "data_type": str(getattr(actual, "type", None) or "UNKNOWN")[:128],
            "nullable": record.nullable,
            "default_value": record.default_value,
            "is_pk": record.is_pk,
            "is_fk": record.is_fk,
            **reference_values(record),
            "is_unique": record.is_unique,
            "unit": record.unit,
            "format": record.format,
            "business_term": record.business_term,
            "temporal_kind": record.temporal_kind,
            "semantic_role": record.semantic_role,
            "aggregations": json_list(record.aggregations),
            "synonyms": json_list(record.synonyms),
            "description": record.description,
            "contains_pii": bool(record.contains_pii),
            "transformation": transformations.get(record.id),
        }

    return {
        "dataset_id": dataset.id,
        "dataset_name": dataset.table_name,
        "display_name": dictionary.display_name,
        "description": dictionary.description,
        "grain": dictionary.grain,
        "create_column": dictionary.create_column,
        "dataset_type": dictionary.dataset_type,
        "layer_id": dictionary.layer_id,
        "time_column": dictionary.time_column,
        "row_kind_column": dictionary.row_kind_column,
        "contains_pii": bool(dictionary.contains_pii),
        "grains": [{"row_kind_value": item.row_kind_value, "label": item.label, "grain": item.grain} for item in grains],
        "read_only": not is_admin(),
        "columns": [column_values(actual) for actual in dataset.columns],
    }


# -------------------------RELATIONSHIP-------------------
def serialize_relationship_contract_fields(contract: RelationshipContract) -> dict[str, Any]:
    """Các trường đã lưu của contract; kết quả kiểm tra dữ liệu chỉ tính khi làm trên bản chụp hiện tại."""
    verification = current_verification(contract)
    verified_at = getattr(contract, "verified_at", None)
    return {
        "id": contract.id,
        "from_dataset_id": contract.from_dataset_id,
        "from_column": contract.from_column,
        "to_dataset_id": contract.to_dataset_id,
        "to_column": contract.to_column,
        "cardinality": contract.cardinality,
        "status": contract.status,
        "source": getattr(contract, "source", None),
        "owner_id": contract.owner_id,
        "approver_id": contract.approver_id,
        "approved_at": iso_datetime(contract.approved_at),
        "revoker_id": contract.revoker_id,
        "revoked_at": iso_datetime(contract.revoked_at),
        "verification": verification,
        "verified_at": verified_at.isoformat() if _verified(contract) and verified_at else None,
    }


def serialize_relationship_contract(contract: RelationshipContract, source: RelationshipEnd, target: RelationshipEnd) -> dict[str, Any]:
    """Contract kèm việc nó còn là bản đã duyệt hiện tại hay không."""
    # Metric execution never joins; a current approved contract on base tables is an edge for schema link instead.
    current = relationship_is_approved_current(contract, source, target)
    return {**serialize_relationship_contract_fields(contract), "current": current, "executable": False}


def serialize_revoked_contract(contract: RelationshipContract, entry: ColumnDictionary | None) -> dict[str, Any]:
    """Contract vừa thu hồi; khi khóa ngoại không còn hai đầu thì chỉ các trường đã lưu."""
    ends = relationship_ends(entry) if entry is not None else None
    if ends is None:
        return {**serialize_relationship_contract_fields(contract), "current": False, "executable": False}
    return serialize_relationship_contract(contract, *ends)


def _verified(contract: RelationshipContract) -> bool:
    verified_hash = getattr(contract, "verified_hash", None)
    return bool(verified_hash) and verified_hash == getattr(contract, "contract_hash", None)
