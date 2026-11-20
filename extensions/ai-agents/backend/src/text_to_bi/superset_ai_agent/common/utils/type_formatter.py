import json
from datetime import date, datetime, timezone
from typing import Any


def iso_datetime(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def sse_event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def iso_date(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value[:10]
    return None


def json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if not value:
        return []
    try:
        items = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [item for item in items if isinstance(item, str)] if isinstance(items, list) else []
