import threading
import time
from collections.abc import Callable
from typing import Any

import requests

from text_to_bi.superset_ai_agent.common.public import public_result

from ....core.config import settings
from ..exceptions import SemanticLayerRefusedError, SemanticLayerUnavailableError

SEMANTIC_LAYER_API = "/extensions/text-to-bi/superset-semantic-layer/semantic-layer"
AGENT_QUERY_API = "/extensions/text-to-bi/superset-ai-agent/semantic-query"
EXPERT_RULES_API = "/extensions/text-to-bi/superset-semantic-layer/expert-rules/expert-rules"
REQUEST_TIMEOUT_SECONDS = 20
# Approved content changes rarely; a user's follow-up questions reuse what was read a moment ago.
CACHE_SECONDS = 60

_cache_lock = threading.Lock()


def internal_superset_url() -> str:
    """Superset as seen from inside its own container; the Compose service listens on 8088."""
    return settings.TEXT_TO_BI_SUPERSET_INTERNAL_URL.rstrip("/")


def get_json(path: str, cookie_header: str, *, preserve_status: bool = False) -> dict[str, Any]:
    """GET as the asking user; raises SemanticLayerUnavailableError when the answer is not a 200."""
    try:
        response = requests.get(
            internal_superset_url() + path,
            headers={"Cookie": cookie_header, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise SemanticLayerUnavailableError() from error
    if response.status_code in (401, 403):
        error = SemanticLayerUnavailableError("Bạn chưa có quyền đọc dữ liệu quản trị nghiệp vụ của Semantic Layer.")
        if preserve_status:
            error.status = response.status_code
        raise error
    if response.status_code != 200:
        error = SemanticLayerUnavailableError(f"Semantic Layer trả về lỗi {response.status_code}.")
        if preserve_status and response.status_code in (400, 404, 409, 429):
            error.status = response.status_code
        raise error
    try:
        answer = response.json()
    except (TypeError, ValueError) as error:
        raise SemanticLayerUnavailableError("Response public không đúng schema được hỗ trợ.") from error
    if not isinstance(answer, dict):
        raise SemanticLayerUnavailableError("Response public không đúng schema được hỗ trợ.")
    return answer


def post_json(path: str, body: dict[str, Any], cookie_header: str, csrf_token: str, action: str) -> dict[str, Any]:
    """POST as the asking user to `action` (\"chạy truy vấn\"); a refusal carries the Semantic Layer's own message."""
    try:
        response = requests.post(
            internal_superset_url() + path,
            json=body,
            headers={"Cookie": cookie_header, "X-CSRFToken": csrf_token, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        unavailable = SemanticLayerRefusedError(f"Không kết nối được tới Semantic Layer để {action}.")
        unavailable.status = 503
        raise unavailable from error
    try:
        answer = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
        if not isinstance(answer, dict):
            raise TypeError("Expected an object response.")
    except (TypeError, ValueError) as cause:
        invalid = SemanticLayerRefusedError("Response public không đúng schema được hỗ trợ.")
        invalid.status = 503
        raise invalid from cause
    if response.status_code not in (200, 201):
        message = answer.get("message") if isinstance(answer.get("message"), str) else None
        preserved = response.status_code in (400, 401, 403, 404, 409, 429)
        error = SemanticLayerRefusedError((message or f"Semantic Layer trả về lỗi {response.status_code} khi {action}.") if preserved else "Semantic Layer chưa sẵn sàng.")
        error.status = response.status_code if preserved else 503
        raise error
    return answer


def cached(store: dict, key: Any, load: Callable[[], Any]) -> Any:
    """What `load` returns for `key`, read again after `CACHE_SECONDS`; keyed by user because access differs."""
    now = time.monotonic()
    with _cache_lock:
        entry = store.get(key)
    if entry and now - entry[0] < CACHE_SECONDS:
        return entry[1]
    value = load()
    with _cache_lock:
        store[key] = (now, value)
    return value


def get_public_json(path: str, cookie_header: str) -> dict[str, Any]:
    try:
        return public_result(get_json(path, cookie_header, preserve_status=True))
    except ValueError as error:
        raise SemanticLayerUnavailableError("Response public không đúng schema được hỗ trợ.") from error


def post_public_json(path: str, body: Any, cookie_header: str, csrf_token: str, action: str) -> dict[str, Any]:
    answer = post_json(path, body, cookie_header, csrf_token, action)
    try:
        return public_result(answer)
    except ValueError as cause:
        error = SemanticLayerRefusedError("Response public không đúng schema được hỗ trợ.")
        error.status = 503
        raise error from cause
