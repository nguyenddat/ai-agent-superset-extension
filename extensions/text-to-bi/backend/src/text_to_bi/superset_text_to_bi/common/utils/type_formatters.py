import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python

Scalar = str | int | float | bool | Decimal | UUID | date | datetime | None
JsonScalar = str | int | float | bool | None


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ISO 8601 UTC with microseconds and a Z suffix.
def iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return utc_datetime(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_datetime(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO 8601 string")
    text = value.strip()
    try:
        # Python 3.10's fromisoformat does not read the Z suffix.
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as error:
        raise ValueError("timestamp must be ISO 8601") from error
    return utc_datetime(parsed)


def iso_date(value: date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise TypeError("iso_date expects a date, not a datetime")
    return value.isoformat()


# Keeps JSON primitive types and normalizes precise or temporal values.
def format_scalar(value: Scalar) -> JsonScalar:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not valid JSON values")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite decimals are not valid JSON values")
        return format(value, "f")
    if isinstance(value, datetime):
        return iso_datetime(value)
    if isinstance(value, date):
        return iso_date(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported scalar type: {type(value).__name__}")


def sse_event(name: str, data: Any) -> str:
    return f"event: {name}\ndata: {json.dumps(to_jsonable_python(data), ensure_ascii=False)}\n\n"
