from typing import Any

from superset.connectors.sqla.models import SqlaTable
from superset.sql.parse import SQLGLOT_DIALECTS

from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_datasets

from ...data_dictionary.dependencies import (
    column_dictionary_repository,
    column_transformation_repository,
    dataset_dictionary_repository,
)
from ...data_dictionary.models import DatasetDictionary
from ..dependencies import data_layer_repository, lineage_edge_repository
from ..models import BusinessDomain, DataLayer, LineageEdge
from .lineage_overrides import EdgeKey, flipped_key, match_override
from .metric_columns import metric_columns
from .transformation_edges import transformation_edges

# "flow" and "relation" are reference edges from PK/FK declarations; "transform" edges come from the column
# transformations administrators declare.
EDGE_KINDS = ("flow", "relation", "transform")


def _classify_reference(referencing_id: int, referenced_id: int, ranks: dict[int, int]) -> tuple[str, int, int]:
    referencing_rank, referenced_rank = ranks.get(referencing_id), ranks.get(referenced_id)
    if referencing_rank is not None and referenced_rank is not None and referenced_rank < referencing_rank:
        return "flow", referenced_id, referencing_id
    return "relation", referencing_id, referenced_id


def infer_dictionary_edges(datasets: dict[int, SqlaTable]) -> dict[tuple[int, int, str], dict[str, Any]]:
    ranks = data_layer_repository().levels_for_datasets(datasets)
    column_repository = column_dictionary_repository()
    rows = column_repository.read_references(datasets)
    # Dictionary rows outlive columns dropped or renamed in Superset, so only live columns may produce edges.
    live_columns = {
        dataset_id: {str(column.column_name) for column in dataset.columns} for dataset_id, dataset in datasets.items()
    }
    # A PK column is only unique on its own when it is the whole key; part of a composite key repeats per row.
    pk_counts: dict[int, int] = {}
    for dataset_id, column_name in column_repository.read_primary_key_names(datasets):
        if column_name in live_columns[dataset_id]:
            pk_counts[dataset_id] = pk_counts.get(dataset_id, 0) + 1
    edges: dict[tuple[int, int, str], dict[str, Any]] = {}
    for column, referenced_column in rows:
        source_dataset = datasets.get(column.dataset_id)
        target_dataset = datasets.get(referenced_column.dataset_id)
        if source_dataset is None or target_dataset is None or source_dataset.id == target_dataset.id:
            continue
        if (
            column.column_name not in live_columns[source_dataset.id]
            or referenced_column.column_name not in live_columns[target_dataset.id]
        ):
            continue
        kind, source_id, target_id = _classify_reference(source_dataset.id, target_dataset.id, ranks)
        key = (source_id, target_id, kind)
        edge = edges.setdefault(
            key,
            {
                "source": key[0],
                "target": key[1],
                "kind": kind,
                "origin": "dictionary",
                "label": None,
                "columns": [],
                "column_links": [],
            },
        )
        edge["columns"].append(f"{column.column_name} → {referenced_column.column_name}")
        # Column pairs follow the edge's direction: relation edges start at the FK column, flow edges at the key.
        pair = (column.column_name, referenced_column.column_name)
        source_column, target_column = pair if kind == "relation" else pair[::-1]
        edge["column_links"].append({"source": source_column, "target": target_column})
        # The referenced table is the "1" side; the referencing table is "1" only when the FK column is unique by
        # itself. Relation edges point from the referencing table, flow edges from the referenced one.
        unique_alone = column.is_unique or (column.is_pk and pk_counts.get(column.dataset_id, 0) == 1)
        referencing_end = "source_cardinality" if kind == "relation" else "target_cardinality"
        referenced_end = "target_cardinality" if kind == "relation" else "source_cardinality"
        many = not unique_alone or edge.get(referencing_end) == "n"
        edge[referencing_end] = "n" if many else "1"
        edge[referenced_end] = "1"
        edge["label"] = f"{edge['source_cardinality']}:{edge['target_cardinality']}"
    return edges


def infer_transformation_edges(datasets: dict[int, SqlaTable]) -> dict[tuple[int, int, str], dict[str, Any]]:
    rows = column_transformation_repository().read_into_datasets(datasets)
    table_names = {dataset_id: str(dataset.table_name) for dataset_id, dataset in datasets.items()}
    # A column's inputs may sit on another database; they are named in its list of inputs but draw no edge.
    elsewhere = {source.dataset_id for _, _, source in rows} - table_names.keys()
    table_names.update({dataset.id: str(dataset.table_name) for dataset in get_datasets(elsewhere)})
    live_columns = {
        dataset_id: {str(column.column_name) for column in dataset.columns} for dataset_id, dataset in datasets.items()
    }
    return transformation_edges(rows, table_names, live_columns)


def infer_edges(datasets: dict[int, SqlaTable]) -> dict[tuple[int, int, str], dict[str, Any]]:
    return {**infer_dictionary_edges(datasets), **infer_transformation_edges(datasets)}


def lineage_edges(datasets: dict[int, SqlaTable]) -> list[dict[str, Any]]:
    edges = infer_edges(datasets)
    overrides = lineage_edge_repository().between(datasets)
    rows = {(row.source_dataset_id, row.target_dataset_id, row.kind): row for row in overrides}
    inferred = set(edges)
    used: set[int] = set()
    for key in inferred:
        override = match_override(key, inferred, rows)
        if override is None:
            edges[key]["color"] = None
            continue
        used.add(override.id)
        # A declared transformation is always drawn; a hidden row stored for one before it could not be hidden is
        # ignored, since the canvas offers no way to show it again.
        if override.is_hidden and key[2] != "transform":
            del edges[key]
        else:
            edges[key]["color"] = override.color
    for override in overrides:
        key = (override.source_dataset_id, override.target_dataset_id, override.kind)
        if override.id in used or override.is_hidden:
            continue
        if override.is_manual and key not in edges:
            edges[key] = {
                "source": key[0],
                "target": key[1],
                "kind": override.kind,
                "origin": "manual",
                "label": override.label,
                "color": override.color,
                "columns": [],
                "column_links": [],
            }
    return sorted(edges.values(), key=lambda edge: (edge["source"], edge["target"], edge["kind"]))


def find_edge_override(key: EdgeKey, inferred: dict[EdgeKey, Any]) -> LineageEdge | None:
    rows = {
        (row.source_dataset_id, row.target_dataset_id, row.kind): row
        for row in lineage_edge_repository().for_keys(key, flipped_key(key))
    }
    row = match_override(key, inferred, rows)
    if row is not None and (row.source_dataset_id, row.target_dataset_id, row.kind) != key:
        row.source_dataset_id, row.target_dataset_id, row.kind = key
    return row


def dataset_metrics(datasets: dict[int, SqlaTable]) -> list[dict[str, Any]]:
    metrics = []
    for dataset in datasets.values():
        dialect = SQLGLOT_DIALECTS.get(dataset.database.db_engine_spec.engine)
        column_names = [column.column_name for column in dataset.columns]
        for metric in dataset.metrics:
            expression = str(metric.expression or "").replace(" ", "").upper()
            if metric.metric_name == "count" or expression == "COUNT(*)":
                continue
            metrics.append(
                {
                    "id": metric.id,
                    "dataset_id": dataset.id,
                    "metric_name": metric.metric_name,
                    "verbose_name": metric.verbose_name,
                    "description": metric.description,
                    "expression": metric.expression,
                    "columns": metric_columns(metric.expression, column_names, dialect),
                }
            )
    return metrics


def serialize_layer(layer: DataLayer) -> dict[str, Any]:
    return {
        "id": layer.id,
        "name": layer.name,
        "description": layer.description,
        "color": layer.color,
        "sort_order": layer.sort_order,
        "level": layer.level,
    }


def dataset_classifications(dataset_ids: list[int]) -> dict[str, dict[str, Any]]:
    rows = dataset_dictionary_repository().read_classifications(dataset_ids)
    return {
        str(dataset_id): {"layer_id": layer_id, "dataset_type": dataset_type}
        for dataset_id, layer_id, dataset_type in rows
    }


def serialize_domain(domain: BusinessDomain, dataset_ids: set[int] | None = None) -> dict[str, Any]:
    ids = sorted(dataset.id for dataset in domain.datasets)
    return {
        "id": domain.id,
        "name": domain.name,
        "description": domain.description,
        "color": domain.color,
        "dataset_ids": [dataset_id for dataset_id in ids if dataset_ids is None or dataset_id in dataset_ids],
    }


def ensure_dataset_dictionaries(datasets: list[SqlaTable]) -> None:
    repository = dataset_dictionary_repository()
    existing = repository.read_existing_ids(dataset.id for dataset in datasets)
    for dataset in datasets:
        if dataset.id not in existing:
            repository.add(
                DatasetDictionary(
                    id=dataset.id,
                    dataset_name=dataset.table_name,
                    display_name=dataset.table_name,
                    description=dataset.description,
                ),
                flush=False,
            )
    repository.flush()
