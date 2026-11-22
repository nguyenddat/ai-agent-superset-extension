from typing import TypeVar

from flask import request
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from .exceptions import QueryParameterError, RequestBodyError

Schema = TypeVar("Schema", bound=BaseModel)


# The client sees one safe message, as in the standalone API: Pydantic's details may echo what was sent.
def request_body(schema: type[Schema]) -> Schema:
    try:
        return schema.model_validate(request.get_json(silent=True))
    except PydanticValidationError as error:
        raise RequestBodyError() from error


def query_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise QueryParameterError(f"{name} phải là số nguyên từ {minimum} đến {maximum}.") from error
    if not minimum <= value <= maximum:
        raise QueryParameterError(f"{name} phải là số nguyên từ {minimum} đến {maximum}.")
    return value
