from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from ..exceptions import SemanticLayerUnavailableError
from .client import AGENT_QUERY_API, EXPERT_RULES_API, SEMANTIC_LAYER_API, cached, get_public_json

# Expert rule operators and the metric query operators they become; a rule using any other one cannot be run.
RULE_OPERATORS = {
    "equals": "==",
    "not_equals": "!=",
    "greater_than": ">",
    "greater_than_or_equal": ">=",
    "less_than": "<",
    "less_than_or_equal": "<=",
    "in": "IN",
    "not_in": "NOT IN",
}


@dataclass
class SemanticCatalog:
    glossary_terms: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    expert_rules: list[dict[str, Any]] = field(default_factory=list)
    # Each dataset with approved metrics: its columns, and the labelled values of its key columns.
    datasets: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "glossary_terms": [term["name"] for term in self.glossary_terms],
            "metrics": [metric["name"] for metric in self.metrics],
            "expert_rules": [rule["name"] for rule in self.expert_rules],
        }


def _condition_text(condition: dict[str, Any], column_names: dict[str, str]) -> str:
    column_id = str(condition.get("field_ref", {}).get("column_dictionary_id"))
    return f"{column_names.get(column_id, column_id)} {condition.get('operator')} {condition.get('value')}"


def rule_filters(rule: dict[str, Any]) -> list[dict[str, Any]] | None:
    columns = rule.get("condition_columns") or {}
    filters = []
    for condition in rule.get("conditions", []):
        column = columns.get(str(condition.get("field_ref", {}).get("column_dictionary_id")))
        operator = RULE_OPERATORS.get(condition.get("operator"))
        if not column or not operator:
            return None
        filters.append({"column": column, "operator": operator, "value": condition.get("value")})
    return filters


def dataset_entry(dataset: dict[str, Any], members: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": dataset["id"],
        "name": dataset.get("name"),
        "columns": [
            {
                key: column.get(key)
                for key in ("name", "label", "type", "temporal", "groupby", "filterable")
                if column.get(key) not in (None, "")
            }
            for column in dataset.get("dimensions", [])
        ],
        "labelled_values": [
            {
                "column": item["key_column"],
                # The column holding the labels as stored, when it is not a calculated one; a filter on it uses them.
                "label_column": item.get("label_column"),
                "label": item.get("label"),
                "values": [{"value": member["value"], "label": member["label"]} for member in item.get("members", [])],
            }
            for item in members.get("dimensions", [])
        ],
        # The first and last date of each date column, so a question outside them is known to have no data.
        "time_ranges": members.get("time_ranges", []),
    }


def query_defaults_entry(defaults: dict[str, Any] | None) -> dict[str, Any] | None:
    if not defaults:
        return None
    return {key: value for key, value in defaults.items() if value not in (None, "", [])} or None


def term_entry(term: dict[str, Any], metric_keys: set[tuple[int, int]]) -> dict[str, Any]:
    links = term.get("links") or []
    return {
        "id": term["term_id"],
        "name": term["canonical_name"],
        "synonyms": term.get("synonyms") or [],
        "definition": term.get("definition"),
        "metrics": [
            {"dataset_id": link["dataset_id"], "metric_id": link["metric_id"]}
            for link in links
            if link.get("kind") == "metric" and (link["dataset_id"], link.get("metric_id")) in metric_keys
        ],
        "columns": [
            {"dataset_id": link["dataset_id"], "column": link["column_name"]}
            for link in links
            if link.get("kind") == "column" and link.get("column_name")
        ],
        "dataset_ids": [link["dataset_id"] for link in links if link.get("kind") == "dataset"],
    }


def flatten_catalog(
    catalog: dict[str, Any],
    glossary: dict[str, Any],
    rules: dict[str, Any],
    members_by_dataset: dict[int, dict[str, Any]] | None = None,
) -> SemanticCatalog:
    metric_keys = {
        (dataset["id"], metric["metric_id"])
        for dataset in catalog.get("datasets", [])
        for metric in dataset.get("metrics", [])
    }
    terms = [term_entry(term, metric_keys) for term in glossary.get("terms", [])]
    metrics = [
        {
            "dataset_id": dataset["id"],
            "dataset_name": dataset.get("name"),
            "metric_id": metric["metric_id"],
            "name": metric.get("verbose_name") or metric["metric_name"],
            "metric_name": metric["metric_name"],
            "definition": metric.get("business_definition") or metric.get("description"),
            "unit": metric.get("unit"),
            "d3format": metric.get("d3format"),
            "glossary_term_ids": [term["term_id"] for term in metric.get("glossary_terms") or []],
            "query_defaults": query_defaults_entry(metric.get("query_defaults")),
        }
        for dataset in catalog.get("datasets", [])
        for metric in dataset.get("metrics", [])
    ]
    expert_rules = [
        {
            "id": rule["id"],
            "name": rule["name"],
            "dataset_id": rule.get("dataset_id"),
            "conditions": [
                _condition_text(condition, rule.get("column_names") or {}) for condition in rule.get("conditions", [])
            ],
            "filters": rule_filters(rule),
            "exceptions": [f"{item['when']} → {item['outcome']}" for item in rule.get("exceptions", [])],
            "example_questions": [item["question"] for item in rule.get("examples", [])],
            "metric_ids": rule.get("metric_ids") or [],
            "glossary_term_ids": rule.get("glossary_term_ids") or [],
        }
        for rule in rules.get("rules", [])
    ]
    datasets = [
        dataset_entry(dataset, (members_by_dataset or {}).get(dataset["id"], {}))
        for dataset in catalog.get("datasets", [])
        if dataset.get("metrics")
    ]
    return SemanticCatalog(glossary_terms=terms, metrics=metrics, expert_rules=expert_rules, datasets=datasets)


def dimension_members(dataset_id: int, cookie_header: str) -> dict[str, Any]:
    try:
        return get_public_json(f"{AGENT_QUERY_API}/dataset/{dataset_id}/dimension-members", cookie_header)
    except SemanticLayerUnavailableError:
        return {}


def load_semantic_catalog(cookie_header: str) -> SemanticCatalog:
    paths = (
        f"{AGENT_QUERY_API}/semantic-catalog",
        f"{SEMANTIC_LAYER_API}/glossary/discovery",
        f"{EXPERT_RULES_API}/discover",
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        catalog, glossary, rules = pool.map(lambda path: get_public_json(path, cookie_header), paths)
        dataset_ids = [dataset["id"] for dataset in catalog.get("datasets", []) if dataset.get("metrics")]
        found = pool.map(lambda dataset_id: dimension_members(dataset_id, cookie_header), dataset_ids)
        members = dict(zip(dataset_ids, found))
    return flatten_catalog(catalog, glossary, rules, members)


_cached_catalogs: dict[int, tuple[float, SemanticCatalog]] = {}


def cached_semantic_catalog(user_id: int, cookie_header: str) -> SemanticCatalog:
    return cached(_cached_catalogs, user_id, lambda: load_semantic_catalog(cookie_header))
