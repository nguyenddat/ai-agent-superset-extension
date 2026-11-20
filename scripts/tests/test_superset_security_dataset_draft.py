"""Exercise RLS source exclusion for both draft validation and creation."""

import ast
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "extensions/semantic-layer/backend/src/text_to_bi/superset_semantic_layer/modules/data_dictionary"


def draft_sources(attached_rules, for_agent, effective_filters=None):
    source = (MODULES / "routes/route_dataset_draft.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    route = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "DatasetDraftRoutes")
    method = next(node for node in route.body if isinstance(node, ast.FunctionDef) and node.name == "_base_datasets")
    class Dataset:
        def __init__(self, identifier, table_name):
            self.id, self.table_name = identifier, table_name

        @property
        def row_level_security_filters(self):
            return attached_rules(self)

    datasets = [Dataset(1, "public_weather"), Dataset(2, "restricted_weather")]
    namespace = {
        "SqlaTable": Any,
        "BASE_DATASET": "base",
        "dataset_dictionary_repository": lambda: SimpleNamespace(read_by_type=lambda dataset_type: datasets),
        "get_datasets": lambda identifiers: datasets,
        "is_internal_dataset": lambda dataset: False,
        "can_access_dataset": lambda dataset: True,
        # Superset's get_rls_filters() is caller-role-specific. Draft source checks must not rely on it.
        "get_rls_filters": effective_filters or (lambda dataset: []),
        "logger": logging.getLogger(__name__),
    }
    exec(  # noqa: S102
        compile(ast.Module(body=[method], type_ignores=[]), str(MODULES / "routes/route_dataset_draft.py"), "exec"),
        namespace,
    )
    return namespace["_base_datasets"](None, for_agent)


@pytest.mark.parametrize("for_agent", [True, False], ids=["validate", "create"])
def test_rls_source_is_rejected_for_both_draft_paths(for_agent):
    allowed = draft_sources(lambda dataset: ["policy"] if dataset.id == 2 else [], for_agent)
    assert list(allowed) == ["public_weather"]


def test_admin_create_rejects_rule_attached_for_another_role():
    # The dataset backref is the global table-to-RLS relationship in Superset 6.1. An Admin's effective filter list
    # can be empty while another role has a filter attached to a source table.
    allowed = draft_sources(
        lambda dataset: [SimpleNamespace(roles=["restricted_role"])] if dataset.id == 2 else [],
        False,
        effective_filters=lambda dataset: [],
    )
    assert list(allowed) == ["public_weather"]


@pytest.mark.parametrize("for_agent", [True, False], ids=["validate", "create"])
def test_rls_inspection_failure_excludes_source(for_agent):
    def filters(dataset):
        if dataset.id == 2:
            raise RuntimeError("sensitive policy detail")
        return []

    assert list(draft_sources(filters, for_agent)) == ["public_weather"]


def sql_validator():
    source = (MODULES / "services/srv_dataset_draft.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    method = next(
        node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "checked_dataset_sql"
    )

    class DatasetDraftValidationError(Exception):
        status = 400

    namespace = {
        "Any": Any,
        "DATASET_SQL_MAX_LENGTH": 10000,
        "DatasetDraftValidationError": DatasetDraftValidationError,
        "SqlglotError": SqlglotError,
        "sqlglot": sqlglot,
        "exp": exp,
        "_WRITING_NODES": (exp.Insert, exp.Update, exp.Delete),
        "_SERVER_FUNCTION_PREFIXES": (),
        "_IDENTIFIER": re.compile(r"^[a-z][a-z0-9_]*$"),
        "CheckedDatasetSql": lambda *values: values,
    }
    exec(  # noqa: S102
        compile(ast.Module(body=[method], type_ignores=[]), str(MODULES / "services/srv_dataset_draft.py"), "exec"),
        namespace,
    )
    return namespace["checked_dataset_sql"], DatasetDraftValidationError


def test_excluded_source_produces_safe_validation_error():
    checked_dataset_sql, DatasetDraftValidationError = sql_validator()
    allowed = draft_sources(lambda dataset: ["policy"] if dataset.id == 2 else [], True)
    with pytest.raises(DatasetDraftValidationError) as error:
        checked_dataset_sql("SELECT temperature FROM restricted_weather", allowed)
    assert error.value.status == 400
    assert "restricted_weather" in str(error.value)
    assert "policy" not in str(error.value)


def test_cte_alias_cannot_hide_restricted_physical_table():
    checked_dataset_sql, DatasetDraftValidationError = sql_validator()
    allowed = draft_sources(lambda dataset: ["policy"] if dataset.id == 2 else [], True)
    query = (
        "WITH restricted_weather AS (SELECT temperature, id FROM restricted_weather) "
        "SELECT p.id FROM public_weather p JOIN restricted_weather r ON p.id = r.id"
    )
    with pytest.raises(DatasetDraftValidationError) as error:
        checked_dataset_sql(query, allowed)
    assert error.value.status == 400
    assert "WITH" in str(error.value)


def test_plain_select_over_allowed_table_still_passes():
    checked_dataset_sql, _ = sql_validator()
    allowed = draft_sources(lambda dataset: ["policy"] if dataset.id == 2 else [], True)
    normalized, columns, sources = checked_dataset_sql("SELECT id FROM public_weather", allowed)
    assert "public_weather" in normalized
    assert columns == ["id"]
    assert [dataset.id for dataset in sources] == [1]


def test_ready_idempotent_retry_revalidates_source_before_returning_dataset():
    source = (MODULES / "routes/route_dataset_draft.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    route = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "DatasetDraftRoutes")
    create = next(
        node for node in route.body if isinstance(node, ast.FunctionDef) and node.name == "create_dataset_draft"
    )
    validation = next(
        node for node in ast.walk(create)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "checked_dataset_proposal"
    )
    ready_return = next(
        node for node in ast.walk(create)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Call)
        and any(
            isinstance(keyword.value, ast.Call) and isinstance(keyword.value.func, ast.Name)
            and keyword.value.func.id == "public_payload"
            for keyword in node.value.keywords
        )
    )
    assert validation.lineno < ready_return.lineno
