import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from ..exceptions import ExpertRuleValidationError
from .srv_expert_rule_sql import contains_sql_or_control

MAX_NAME = 255
MAX_ITEMS = 50
MAX_TEXT = 2_000
MAX_REASON = 512
CONTENT_FIELDS = {
    "schema_version",
    "name",
    "dataset_id",
    "conditions",
    "exceptions",
    "examples",
    "glossary_term_ids",
    "metric_ids",
}
CONDITION_OPERATORS = frozenset(
    {
        "equals", "not_equals", "contains", "not_contains", "greater_than", "greater_than_or_equal",
        "less_than", "less_than_or_equal", "in", "not_in", "is_null", "is_not_null",
    }
)
VALUE_TYPES = frozenset({"string", "number", "boolean", "null", "array"})
_URL = re.compile(r"\b(?:[a-z][a-z0-9+.-]*://|www\.)", re.IGNORECASE)
_SECRET = re.compile(
    r"\b(?:api[-_ ]?key|access[-_ ]?token|secret|password|passwd|authorization|bearer|credential)\b\s*(?:[:=]|\S)",
    re.IGNORECASE,
)


# -------------------------FIELDS-------------------------
def checked_text(value: Any, field: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not (clean := " ".join(value.split())) or len(clean) > limit:
        raise ExpertRuleValidationError(f"Invalid {field}.")
    # Rule values are declarative prose, never a transport for executable SQL, links or credentials. URLs are
    # rejected wholesale so query credentials cannot be smuggled in through harmless-looking parameters.
    if contains_sql_or_control(clean) or _URL.search(clean) or _SECRET.search(clean):
        raise ExpertRuleValidationError(f"Unsafe {field}.")
    return clean


def review_reason(value: Any) -> str | None:
    if value is None:
        return None
    return checked_text(value, "reason", MAX_REASON)


def expected_revision_of(payload: Any) -> int:
    value = payload.get("expected_revision") if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExpertRuleValidationError("expected_revision is required.")
    return value


def group_id_of(payload: Any) -> int | None:
    group_id = payload.get("group_id") if isinstance(payload, dict) else None
    if group_id is not None and (isinstance(group_id, bool) or not isinstance(group_id, int)):
        raise ExpertRuleValidationError("Nhóm rule không hợp lệ.")
    return group_id


def normalized_name(value: str) -> str:
    return " ".join(value.split()).casefold()


# -------------------------PAYLOADS-----------------------
def normalize_group_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - {"name", "description"}:
        raise ExpertRuleValidationError("Nhóm rule chỉ có tên và mô tả.")
    if not isinstance(payload.get("name"), str) or not payload["name"].strip():
        raise ExpertRuleValidationError("Nhập tên nhóm rule.")
    name = checked_text(payload["name"], "name", MAX_NAME)
    description = payload.get("description")
    if description is not None and not isinstance(description, str):
        raise ExpertRuleValidationError("Mô tả nhóm rule không hợp lệ.")
    description = checked_text(description, "description", MAX_TEXT) if description and description.strip() else None
    return {"name": name, "normalized_name": name.casefold(), "description": description}


def normalize_rule_payload(payload: Any, column_resolver: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - CONTENT_FIELDS:
        raise ExpertRuleValidationError("Unsupported expert-rule fields.")
    dataset_id = payload.get("dataset_id")
    if isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
        raise ExpertRuleValidationError("Invalid dataset_id.")
    schema_version = payload.get("schema_version", 1)
    if schema_version not in {1, 2}:
        raise ExpertRuleValidationError("Invalid schema_version.")
    return {
        "schema_version": 2,
        "name": checked_text(payload.get("name"), "name", MAX_NAME),
        "normalized_name": normalized_name(payload["name"]),
        "dataset_id": dataset_id,
        "conditions": _conditions(payload.get("conditions"), schema_version, dataset_id, column_resolver),
        # Many rules hold without exception; examples stay required because they show how the rule is asked about.
        "exceptions": _items(payload.get("exceptions"), "exceptions", {"when", "outcome"}, allow_empty=True),
        "examples": _items(payload.get("examples"), "examples", {"question", "intent"}),
        "glossary_term_ids": _id_list(payload.get("glossary_term_ids", []), "glossary_term_ids"),
        "metric_ids": _id_list(payload.get("metric_ids", []), "metric_ids"),
    }


def without_group(payload: Any) -> Any:
    return {key: value for key, value in payload.items() if key != "group_id"} if isinstance(payload, dict) else payload


def content_hash(values: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# -------------------------HELPERS------------------------
def _id_list(value: Any, field: str) -> list[int]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ExpertRuleValidationError(f"Invalid {field}.")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ExpertRuleValidationError(f"Invalid {field}.")
    if len(set(value)) != len(value):
        raise ExpertRuleValidationError(f"Duplicate {field}.")
    return value


def _items(value: Any, field: str, keys: set[str], allow_empty: bool = False) -> list[dict[str, str]]:
    if not isinstance(value, list) or (not value and not allow_empty) or len(value) > MAX_ITEMS:
        raise ExpertRuleValidationError(f"Invalid {field}.")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != keys:
            raise ExpertRuleValidationError(f"Invalid {field}.")
        result.append({key: checked_text(item[key], f"{field}.{key}") for key in keys})
    return result


def _condition_value_is_valid(value_type: str, value: Any) -> bool:
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "null":
        return value is None
    return isinstance(value, list) and all(item is None or isinstance(item, (str, int, float, bool)) for item in value)


def _resolve_column(column_resolver: Callable[[Any], Any] | None, reference: Any, dataset_id: int) -> Any:
    if column_resolver is None:
        return None
    resolved = column_resolver(reference)
    candidates = resolved if isinstance(resolved, list) else [resolved]
    matches = [
        column for column in candidates if column is not None and getattr(column, "dataset_id", None) == dataset_id
    ]
    if len(matches) != 1:
        raise ExpertRuleValidationError("Invalid condition field reference.")
    return matches[0]


def _legacy_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    return "string" if isinstance(value, str) else "invalid"


def _conditions(
    value: Any, schema_version: int, dataset_id: int, column_resolver: Callable[[Any], Any] | None
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ExpertRuleValidationError("Invalid conditions.")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ExpertRuleValidationError("Invalid conditions.")
        if schema_version == 1:
            if set(item) != {"field", "operator", "value"} or not isinstance(item["field"], str):
                raise ExpertRuleValidationError("Invalid legacy conditions.")
            column = _resolve_column(column_resolver, item["field"], dataset_id)
            if column is None:
                raise ExpertRuleValidationError("Column resolver is required.")
            item = {
                "field_ref": {"column_dictionary_id": column.id},
                "operator": item["operator"],
                "value_type": _legacy_value_type(item["value"]),
                "value": item["value"],
            }
        if (
            set(item) != {"field_ref", "operator", "value_type", "value"}
            or not isinstance(item["field_ref"], dict)
            or set(item["field_ref"]) != {"column_dictionary_id"}
        ):
            raise ExpertRuleValidationError("Invalid conditions.")
        column_id = item["field_ref"]["column_dictionary_id"]
        if (
            isinstance(column_id, bool)
            or not isinstance(column_id, int)
            or item["operator"] not in CONDITION_OPERATORS
            or item["value_type"] not in VALUE_TYPES
            or not _condition_value_is_valid(item["value_type"], item["value"])
        ):
            raise ExpertRuleValidationError("Invalid conditions.")
        if item["operator"] in {"is_null", "is_not_null"} and item["value"] is not None:
            raise ExpertRuleValidationError("Invalid conditions.")
        if column_resolver is not None:
            _resolve_column(column_resolver, column_id, dataset_id)
        result.append(
            {
                "field_ref": {"column_dictionary_id": column_id},
                "operator": item["operator"],
                "value_type": item["value_type"],
                "value": item["value"],
            }
        )
    return result
