from typing import Any
from urllib.parse import urlencode

from ..exceptions import SemanticLayerUnavailableError
from .client import SEMANTIC_LAYER_API, get_public_json


def rows(payload: dict[str, Any], field: str, identifiers: tuple[str, ...]) -> list[dict[str, Any]]:
    entries = payload.get(field)
    if (
        not isinstance(entries, list)
        or any(
            not isinstance(entry, dict) or any(type(entry.get(key)) is not int or entry[key] < 1 for key in identifiers)
            for entry in entries
        )
    ):
        raise SemanticLayerUnavailableError("Danh sách metadata public không đúng schema.")
    keys = [tuple(entry[key] for key in identifiers) for entry in entries]
    if len(keys) != len(set(keys)):
        raise SemanticLayerUnavailableError("Metadata public có định danh bị trùng.")
    return entries


def dictionary_metadata(cookie: str, database_id: int | None = None) -> dict[str, Any]:
    query = "?" + urlencode({"database_id": database_id}) if database_id is not None else ""
    result = get_public_json(f"{SEMANTIC_LAYER_API}/datasets/query-metadata{query}", cookie)
    datasets = rows(result, "datasets", ("id",))
    if database_id is None and result.get("database", object()) is not None:
        raise SemanticLayerUnavailableError("Metadata database public không đúng schema.")
    if (
        database_id is not None
        and (
            not isinstance(result.get("database"), dict) or type(result["database"].get("id")) is not int
            or result["database"]["id"] != database_id
        )
    ):
        raise SemanticLayerUnavailableError("Metadata không khớp database được yêu cầu.")
    for dataset in datasets:
        if not {"schema", "description", "layer", "grains", "is_virtual", "row_level_security"}.issubset(dataset):
            raise SemanticLayerUnavailableError("Metadata dataset public thiếu trường bắt buộc.")
        if (
            not isinstance(dataset.get("name"), str) or not isinstance(dataset.get("database"), dict)
            or type(dataset["database"].get("id")) is not int or dataset["database"]["id"] < 1
        ):
            raise SemanticLayerUnavailableError("Định danh dataset public không đúng schema.")
        if database_id is not None and dataset["database"]["id"] != database_id:
            raise SemanticLayerUnavailableError("Metadata dataset không khớp database được yêu cầu.")
        if (
            type(dataset.get("is_virtual")) is not bool or type(dataset.get("row_level_security")) is not bool
            or not isinstance(dataset.get("grains"), list) or "layer" not in dataset
        ):
            raise SemanticLayerUnavailableError("Thuộc tính dataset public không đúng schema.")
        if (
            not isinstance(dataset.get("columns"), list) or not isinstance(dataset.get("dictionary_columns"), list)
            or not isinstance(dataset.get("dictionary"), dict)
        ):
            raise SemanticLayerUnavailableError("Metadata dataset public không đúng schema.")
        dictionary_fields = {
            "display_name", "description", "grain", "time_column", "row_kind_column", "dataset_type", "contains_pii",
        }
        if not dictionary_fields.issubset(dataset["dictionary"]):
            raise SemanticLayerUnavailableError("Metadata từ điển public thiếu trường bắt buộc.")
        if any(
            not isinstance(column, dict) or not isinstance(column.get("column_name"), str)
            for column in dataset["columns"] + dataset["dictionary_columns"]
        ):
            raise SemanticLayerUnavailableError("Metadata cột public không đúng schema.")
        live_fields = {
            "column_name", "verbose_name", "type", "is_dttm", "groupby", "filterable", "is_active", "expression",
        }
        dictionary_column_fields = {
            "column_name", "display_name", "description", "business_term", "unit", "temporal_kind", "semantic_role",
            "is_pk", "is_fk", "is_unique", "references",
        }
        if (
            any(not live_fields.issubset(column) for column in dataset["columns"])
            or any(not dictionary_column_fields.issubset(column) for column in dataset["dictionary_columns"])
        ):
            raise SemanticLayerUnavailableError("Metadata cột public thiếu trường bắt buộc.")
        for columns in (dataset["columns"], dataset["dictionary_columns"]):
            names = [column["column_name"] for column in columns]
            if len(names) != len(set(names)):
                raise SemanticLayerUnavailableError("Metadata cột public có định danh bị trùng.")
        if any(
            type(column[flag]) is not bool for column in dataset["columns"]
            for flag in ("is_dttm", "groupby", "filterable", "is_active")
        ):
            raise SemanticLayerUnavailableError("Cờ cột public không đúng schema.")
        if any(
            type(column[flag]) is not bool for column in dataset["dictionary_columns"]
            for flag in ("is_pk", "is_fk", "is_unique")
        ):
            raise SemanticLayerUnavailableError("Cờ từ điển cột public không đúng schema.")
        if type(dataset["dictionary"]["contains_pii"]) is not bool:
            raise SemanticLayerUnavailableError("Cờ dữ liệu cá nhân public không đúng schema.")
        if any(
            not isinstance(grain, dict) or not {"row_kind_value", "label", "grain"}.issubset(grain)
            for grain in dataset["grains"]
        ):
            raise SemanticLayerUnavailableError("Grain dataset public không đúng schema.")
        if (
            dataset["layer"] is not None
            and (not isinstance(dataset["layer"], dict) or not {"id", "name", "level"}.issubset(dataset["layer"]))
        ):
            raise SemanticLayerUnavailableError("Layer dataset public không đúng schema.")
    visible_ids = {dataset["id"] for dataset in datasets}
    for dataset in datasets:
        for column in dataset["dictionary_columns"]:
            reference = column["references"]
            if (
                reference is not None
                and (
                    not isinstance(reference, dict) or type(reference.get("dataset_id")) is not int
                    or reference["dataset_id"] < 1
                    or (database_id is None and reference["dataset_id"] not in visible_ids)
                    or not isinstance(reference.get("column"), str)
                )
            ):
                raise SemanticLayerUnavailableError("Tham chiếu cột public không đúng schema.")
    return result


def metric_metadata(cookie: str) -> dict[str, Any]:
    result = get_public_json(f"{SEMANTIC_LAYER_API}/metrics/query-metadata", cookie)
    rows(result, "metrics", ("metric_id",))
    if not isinstance(result.get("limits"), dict):
        raise SemanticLayerUnavailableError("Giới hạn truy vấn public không đúng schema.")
    required = {
        "metric_name", "label", "expression", "description", "d3format", "state", "origin", "definition", "unit",
        "steward_name", "query_defaults",
    }
    for metric in result["metrics"]:
        if (
            not required.issubset(metric) or not isinstance(metric["metric_name"], str)
            or not isinstance(metric["state"], str)
        ):
            raise SemanticLayerUnavailableError("Metadata metric public không đúng schema.")
        if metric["query_defaults"] is not None and not isinstance(metric["query_defaults"], dict):
            raise SemanticLayerUnavailableError("Mặc định truy vấn public không đúng schema.")
    maximum = result["limits"].get("max_rows")
    if type(maximum) is not int or not 1 <= maximum <= 1000:
        raise SemanticLayerUnavailableError("Giới hạn truy vấn public không đúng schema.")
    return result


def relationship_metadata(cookie: str) -> list[dict[str, Any]]:
    result = get_public_json(f"{SEMANTIC_LAYER_API}/relationships/approved", cookie)
    relationships = rows(result, "relationships", ("id", "from_dataset_id", "to_dataset_id"))
    if len({relationship["id"] for relationship in relationships}) != len(relationships):
        raise SemanticLayerUnavailableError("Metadata quan hệ public có định danh bị trùng.")
    for relationship in relationships:
        if (
            relationship.get("cardinality") not in ("many_to_one", "one_to_one")
            or not isinstance(relationship.get("from_column"), str)
            or not isinstance(relationship.get("to_column"), str)
        ):
            raise SemanticLayerUnavailableError("Metadata quan hệ public không đúng schema.")
    return relationships
