import logging
from typing import Any

from superset import security_manager

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import json_list
from text_to_bi.superset_semantic_layer.core.security import can_access_dataset
from text_to_bi.superset_semantic_layer.modules.business_model.dependencies import data_layer_repository
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import (
    datasets_by_name,
    is_internal_dataset,
    require_database,
)

from ..dependencies import column_dictionary_repository, dataset_grain_repository, relationship_contract_repository
from .srv_relationship_contract import relationship_is_approved_current
from .srv_relationship_lookup import relationship_ends
from .srv_seeding import read_dictionary_snapshot

logger = logging.getLogger(__name__)


def readable_datasets(database_id: int | None = None) -> list[Any]:
    return [
        dataset for dataset in datasets_by_name()
        if (database_id is None or dataset.database_id == database_id) and not is_internal_dataset(dataset)
        and can_access_dataset(dataset)
    ]


def read_query_metadata(database_id: int | None = None) -> dict[str, Any]:
    database = require_database(database_id) if database_id is not None else None
    datasets = readable_datasets(database_id)
    visible_ids = {dataset.id for dataset in readable_datasets()}
    columns = column_dictionary_repository()
    described = []
    for dataset in datasets:
        dictionary, entries = read_dictionary_snapshot(dataset)
        try:
            row_security = bool(security_manager.get_rls_filters(dataset))
        except Exception:
            logger.warning("Could not inspect dataset RLS; excluding it from schema graph", exc_info=True)
            row_security = True
        layer = data_layer_repository().get(dictionary.layer_id) if dictionary.layer_id else None
        dictionary_columns = []
        for entry in entries:
            values = {field: getattr(entry, field) for field in (
                "id", "column_name", "display_name", "data_type", "temporal_kind", "semantic_role", "description",
                "business_term", "unit", "is_pk", "is_fk", "is_unique"
            )}
            values.update(
                aggregations=json_list(entry.aggregations), synonyms=json_list(entry.synonyms),
                contains_pii=bool(entry.contains_pii)
            )
            referenced = columns.read(entry.referenced_column) if entry.referenced_column is not None else None
            values["references"] = (
                {"dataset_id": referenced.dataset_id, "column": referenced.column_name}
                if referenced is not None and referenced.dataset_id in visible_ids else None
            )
            dictionary_columns.append(values)
        described.append({
            "id": dataset.id, "name": dataset.table_name, "schema": dataset.schema, "is_virtual": bool(dataset.sql),
            "description": dataset.description, "row_level_security": row_security,
            "database": {
                "id": dataset.database_id, "name": dataset.database.database_name, "dialect": dataset.database.backend
            },
            "dictionary": {field: getattr(dictionary, field) for field in (
                "display_name", "description", "grain", "time_column", "row_kind_column", "dataset_type", "contains_pii"
            )},
            "dictionary_columns": dictionary_columns,
            "grains": [
                {"row_kind_value": grain.row_kind_value, "label": grain.label, "grain": grain.grain}
                for grain in dataset_grain_repository().read_by_row_kind(dataset.id)
            ],
            "layer": {"id": layer.id, "name": layer.name, "level": layer.level} if layer else None,
            "columns": [
                {field: getattr(column, field, None) for field in (
                    "column_name", "verbose_name", "type", "is_dttm", "groupby", "filterable", "is_active", "expression"
                )}
                for column in dataset.columns
            ],
        })
    return {
        "datasets": described,
        "database": (
            {"id": database.id, "name": database.database_name, "dialect": database.backend}
            if database is not None else None
        ),
    }


def read_approved_relationships() -> dict[str, Any]:
    visible_ids = {dataset.id for dataset in readable_datasets()}
    result = []
    columns = column_dictionary_repository()
    for contract in relationship_contract_repository().read_approved():
        if contract.from_dataset_id not in visible_ids or contract.to_dataset_id not in visible_ids:
            continue
        entry = columns.read_by_column_name(contract.from_dataset_id, contract.from_column)
        ends = relationship_ends(entry) if entry is not None else None
        if ends is None or not relationship_is_approved_current(contract, *ends):
            continue
        result.append({field: getattr(contract, field) for field in (
            "id", "from_dataset_id", "from_column", "to_dataset_id", "to_column", "cardinality"
        )})
    return {"relationships": sorted(result, key=lambda relationship: relationship["id"])}
