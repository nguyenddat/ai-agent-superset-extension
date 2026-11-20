from types import SimpleNamespace
from typing import Any

from text_to_bi.superset_ai_agent.modules.semantic_layer.services.public_metadata import (
    dictionary_metadata,
    relationship_metadata,
)

from .metadata import coded_values, dataset_context
from .schema_graph import GRAPH_VERSION, graph_edges, table_node


def read_schema_graph(database_id: int, cookie: str) -> dict[str, Any]:
    metadata = dictionary_metadata(cookie, database_id)
    nodes, excluded = [], []
    for row in metadata["datasets"]:
        if row["dictionary"]["dataset_type"] != "base" or row["is_virtual"]:
            continue
        if row["row_level_security"]:
            excluded.append({"dataset_id": row["id"], "table": row["name"], "reason": "row_level_security"})
            continue
        dataset, dictionary, entries, grains, layer = dataset_context(row)
        nodes.append(table_node(dataset, dictionary, entries, grains, coded_values(dataset, entries), layer))
    node_ids = {node["dataset_id"] for node in nodes}
    relationships = [SimpleNamespace(**relationship) for relationship in relationship_metadata(cookie)
                     if relationship["from_dataset_id"] in node_ids and relationship["to_dataset_id"] in node_ids]
    return {
        "version": GRAPH_VERSION, "database": metadata["database"], "tables": nodes,
        "edges": graph_edges(relationships), "excluded": excluded,
    }
