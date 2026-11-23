from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from text_to_bi.superset_text_to_bi.common.utils.type_formatters import iso_date, iso_datetime


def json_payload(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso_datetime(value)
    if isinstance(value, date):
        return iso_date(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, BaseModel):
        return json_payload(value.model_dump())
    if isinstance(value, dict):
        return {key: json_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_payload(item) for item in value]
    return value
