from typing import Any

PUBLIC_SCHEMA_VERSION = 1


def public_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": PUBLIC_SCHEMA_VERSION, "result": result}


def public_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != PUBLIC_SCHEMA_VERSION or not isinstance(payload.get("result"), dict):
        raise ValueError("Unsupported public API response schema.")
    return payload["result"]
