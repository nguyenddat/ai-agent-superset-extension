from typing import Any

from text_to_bi.superset_ai_agent.modules.semantic_layer.services.client import SEMANTIC_LAYER_API, get_public_json
from text_to_bi.superset_ai_agent.modules.semantic_layer.services.public_metadata import dictionary_metadata, metric_metadata, relationship_metadata

FILTER_OPERATORS = ["==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN"]


def assemble_catalog(metadata: dict[str, Any], metrics: dict[str, Any], relationships: list[dict[str, Any]], terms: list[dict[str, Any]]) -> dict[str, Any]:
    datasets = {row["id"]: row for row in metadata["datasets"]}
    catalog: dict[int, dict[str, Any]] = {}
    terms_by_metric: dict[int, list[dict[str, Any]]] = {}
    for term in terms:
        for link in term.get("links", []):
            if link.get("kind") == "metric" and link.get("metric_id") is not None:
                terms_by_metric.setdefault(link["metric_id"], []).append({"term_id": term["term_id"], "name": term["canonical_name"], "synonyms": term["synonyms"]})
    for metric in metrics["metrics"]:
        dataset_id = metric["dataset_id"]
        if metric["state"] != "approved" or dataset_id not in datasets:
            continue
        dataset = datasets[dataset_id]
        item = catalog.setdefault(dataset_id, {"id": dataset_id, "name": dataset["name"], "metrics": [], "dimensions": []})
        item["metrics"].append({
            "metric_id": metric["metric_id"], "metric_name": metric["metric_name"], "verbose_name": metric["label"],
            "description": metric["description"], "d3format": metric["d3format"], "query_defaults": metric["query_defaults"],
            "business_definition": metric["definition"], "unit": metric["unit"], "steward_name": metric["steward_name"],
            "glossary_terms": sorted(terms_by_metric.get(metric["metric_id"], []), key=lambda term: term["term_id"]),
        })
    visible = []
    for relationship in relationships:
        ends = (relationship["from_dataset_id"], relationship["to_dataset_id"])
        if not all(dataset_id in datasets for dataset_id in ends):
            continue
        for dataset_id in ends:
            catalog.setdefault(dataset_id, {"id": dataset_id, "name": datasets[dataset_id]["name"], "metrics": [], "dimensions": []})
        visible.append({**relationship, "executable": False})
    for dataset_id, item in catalog.items():
        source = datasets[dataset_id]
        entries = {entry["column_name"]: entry for entry in source["dictionary_columns"]}
        item["contains_pii"] = bool(source["dictionary"]["contains_pii"])
        item["metrics"].sort(key=lambda metric: (metric["metric_name"], metric["metric_id"]))
        for column in source["columns"]:
            if column["is_active"] is not True or column["expression"] or not (column["groupby"] or column["filterable"]):
                continue
            entry = entries.get(column["column_name"], {})
            item["dimensions"].append({"name": column["column_name"], "label": column["verbose_name"] or entry.get("display_name"), "type": column["type"],
                                       "temporal": bool(column["is_dttm"]), "groupby": bool(column["groupby"]), "filterable": bool(column["filterable"]),
                                       "contains_pii": bool(entry.get("contains_pii"))})
    return {"datasets": [catalog[key] for key in sorted(catalog)], "relationships": sorted(visible, key=lambda relationship: relationship["id"]),
            "limits": {"max_rows": metrics["limits"]["max_rows"], "filter_operators": FILTER_OPERATORS, "joins_supported": False}}


def read_catalog(cookie: str) -> dict[str, Any]:
    metadata = dictionary_metadata(cookie)
    metrics = metric_metadata(cookie)
    relationships = relationship_metadata(cookie)
    glossary = get_public_json(f"{SEMANTIC_LAYER_API}/glossary/discovery", cookie)
    return assemble_catalog(metadata, metrics, relationships, glossary.get("terms", []))
