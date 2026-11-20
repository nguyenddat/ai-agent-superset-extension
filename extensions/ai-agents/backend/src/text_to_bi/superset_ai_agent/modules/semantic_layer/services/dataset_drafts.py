from typing import Any

from .client import AGENT_QUERY_API, SEMANTIC_LAYER_API, get_public_json, post_public_json


def dataset_sources(cookie_header: str) -> list[dict[str, Any]]:
    return get_public_json(f"{AGENT_QUERY_API}/data-model/sources", cookie_header).get("datasets", [])


def validate_dataset_draft(body: Any, cookie_header: str, csrf_token: str) -> dict[str, Any]:
    return post_public_json(
        f"{SEMANTIC_LAYER_API}/dataset-drafts/validate", body, cookie_header, csrf_token, "validate dataset draft",
    )["draft"]


def create_dataset_draft(body: dict[str, Any], cookie_header: str, csrf_token: str) -> int:
    return post_public_json(
        f"{SEMANTIC_LAYER_API}/dataset-drafts/create", body, cookie_header, csrf_token, "create dataset draft",
    )["dataset_id"]
