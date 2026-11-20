from collections.abc import Iterable, Mapping
from typing import Any

from .lineage_overrides import EdgeKey


def transformation_edges(
    rows: Iterable[tuple[Any, str | None, Any]],
    table_names: Mapping[int, str],
    live_columns: Mapping[int, set[str]],
) -> dict[EdgeKey, dict[str, Any]]:
    targets: dict[int, tuple[Any, str | None, list[Any]]] = {}
    for target, expression, source in rows:
        if target.column_name in live_columns.get(target.dataset_id, ()):
            targets.setdefault(target.id, (target, expression, []))[2].append(source)
    edges: dict[EdgeKey, dict[str, Any]] = {}
    for target, expression, sources in targets.values():
        mapping = {
            "target_column": target.column_name,
            "expression": expression,
            "sources": [f"{table_names.get(source.dataset_id, '?')}.{source.column_name}" for source in sources],
        }
        for source in sources:
            if source.dataset_id == target.dataset_id or source.column_name not in live_columns.get(
                source.dataset_id, ()
            ):
                continue
            key = (source.dataset_id, target.dataset_id, "transform")
            edge = edges.setdefault(
                key,
                {
                    "source": key[0],
                    "target": key[1],
                    "kind": "transform",
                    "origin": "dictionary",
                    "label": None,
                    "columns": [],
                    "column_links": [],
                    "transformations": [],
                },
            )
            edge["columns"].append(f"{source.column_name} → {target.column_name}")
            edge["column_links"].append({"source": source.column_name, "target": target.column_name})
            if mapping not in edge["transformations"]:
                edge["transformations"].append(mapping)
    return edges
