import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from text_to_bi.superset_text_to_bi.common.base_exceptions import NotFoundError, ValidationError
from text_to_bi.superset_text_to_bi.common.utils.identifiers import uuid7
from text_to_bi.superset_text_to_bi.common.utils.type_formatters import (
    format_scalar,
    iso_datetime,
    parse_datetime,
    sse_event,
)
from text_to_bi.superset_text_to_bi.modules.data_dictionary.exceptions import (
    DataDictionaryValidationError,
    DictionaryAutofillFailedError,
)

PACKAGE = Path(__file__).parents[1] / "src" / "text_to_bi" / "superset_text_to_bi"


def test_uuid7_has_version_variant_and_creation_order():
    ids = [uuid7() for _ in range(2000)]

    assert all(value.version == 7 and value.variant == "specified in RFC 4122" for value in ids)
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    timestamp_ms = ids[0].int >> 80
    assert abs(timestamp_ms - datetime.now(timezone.utc).timestamp() * 1000) < 60_000


@pytest.mark.parametrize("abstract_error", [ValidationError, NotFoundError])
def test_a_root_error_cannot_be_raised_directly(abstract_error):
    with pytest.raises(TypeError):
        abstract_error()


def test_a_module_error_carries_status_code_and_safe_message():
    error = DictionaryAutofillFailedError()

    assert (error.status, error.code, str(error)) == (502, "dictionary_autofill_failed", error.message)
    assert DataDictionaryValidationError("x").status == 422
    assert isinstance(DataDictionaryValidationError("x"), ValueError)


def test_formatters_write_utc_iso_and_keep_precision():
    moment = datetime(2026, 11, 20, 10, 0, tzinfo=timezone(timedelta(hours=7)))

    assert iso_datetime(moment) == "2026-11-20T03:00:00.000000Z"
    assert parse_datetime("2026-11-20T03:00:00Z") == moment
    assert format_scalar(Decimal("1.50")) == "1.50"
    with pytest.raises(ValueError):
        parse_datetime("2026-11-20T03:00:00")
    assert sse_event("done", {"id": UUID(int=1)}) == (
        'event: done\ndata: {"id": "00000000-0000-0000-0000-000000000001"}\n\n'
    )


# The backend runs on Superset's Python 3.10: no syntax or standard library names that came later.
def test_backend_parses_as_python_310_and_avoids_newer_names():
    newer = {("datetime", "UTC"), ("uuid", "uuid7"), ("typing", "Self"), ("enum", "StrEnum")}
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not {(node.module, alias.name) for alias in node.names} & newer, path
            assert not isinstance(node, ast.TypeAlias if hasattr(ast, "TypeAlias") else ()), path
