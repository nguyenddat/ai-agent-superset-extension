import json
import time
from dataclasses import dataclass
from typing import Any

from flask import current_app
from superset import is_feature_enabled
from superset.daos.database import DatabaseDAO
from superset.exceptions import SupersetParseError, SupersetSecurityException
from superset.extensions import security_manager
from superset.models.core import Database
from superset.sql.parse import SQLScript
from superset.sqllab.api import SqlLabRestApi
from superset.sqllab.command_status import SqlJsonExecutionStatus
from superset.sqllab.schemas import ExecutePayloadSchema
from superset.sqllab.sqllab_execution_context import SqlJsonExecutionContext

from text_to_bi.superset_text_to_bi.modules.auth.exceptions import DatasetAccessError, QueryRequiredError
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import can_query_datasets, current_user
from text_to_bi.superset_text_to_bi.modules.superset.exceptions import DatasetNotFoundError
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import readable_datasets

from .sql_guard import validate_select


@dataclass(frozen=True)
class QueryRows:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool
    elapsed_ms: int


def run_superset_read_only(database_id: int, sql: str, max_rows: int) -> QueryRows:
    if isinstance(database_id, bool) or not isinstance(database_id, int) or database_id < 1:
        raise ValueError("database_id must be a positive Superset database ID.")
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer.")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL must not be empty.")

    current_user()
    if not can_query_datasets():
        raise QueryRequiredError()
    if not security_manager.can_access("can_execute_sql_query", "SQLLab"):
        raise QueryRequiredError("Bạn cần quyền can_execute_sql_query trên SQLLab của Superset.")
    if not current_app.config.get("SQLLAB_ENABLED", True):
        raise QueryRequiredError("SQL Lab đang bị tắt trong Superset.")
    if is_feature_enabled("SQLLAB_FORCE_RUN_ASYNC"):
        raise RuntimeError("Text to BI cần truy vấn SQL Lab đồng bộ; Superset hiện buộc chạy bất đồng bộ.")

    database = DatabaseDAO.find_by_id(database_id)
    if database is None:
        raise DatasetNotFoundError()
    if not getattr(database, "expose_in_sqllab", False):
        raise DatasetAccessError("Database này chưa được Superset cho phép truy vấn qua SQL Lab.")
    try:
        security_manager.raise_for_access(database=database)
    except SupersetSecurityException:
        raise DatasetAccessError() from None

    visible_names: dict[str, str] = {}
    short_names: dict[str, list[str]] = {}
    for dataset in readable_datasets():
        if dataset.database_id != database_id:
            continue
        schema = str(dataset.schema or "")
        name = str(dataset.table_name)
        qualified_name = f"{schema}.{name}" if schema else name
        visible_names[qualified_name.lower()] = qualified_name
        short_names.setdefault(name.lower(), []).append(qualified_name)
    for name, candidates in short_names.items():
        if len(candidates) == 1:
            visible_names.setdefault(name, candidates[0])
    sql = validate_select(sql, visible_names)
    _require_single_select(sql, database)

    query_payload = {
        "database_id": database_id,
        "sql": sql,
        "queryLimit": max_rows + 1,
        "runAsync": False,
        "select_as_cta": False,
        "expand_data": False,
        "templateParams": "{}",
        "tab": "Text to BI",
    }
    validated_payload = ExecutePayloadSchema().load(query_payload)
    execution_context = SqlJsonExecutionContext(validated_payload)

    # Superset 6.1 exposes no public in-process command factory; this private factory is also used by its SQL Lab API.
    command = SqlLabRestApi._create_sql_json_command(execution_context, log_params=None)
    started_at = time.perf_counter()
    command_result = command.run()
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)

    if not isinstance(command_result, dict) or command_result.get("status") != SqlJsonExecutionStatus.HAS_RESULTS:
        raise RuntimeError("Superset SQL Lab did not return synchronous query results.")
    serialized_payload = command_result.get("payload")
    if not isinstance(serialized_payload, str):
        raise TypeError("Superset SQL Lab returned an invalid result payload.")
    try:
        result_payload = json.loads(serialized_payload)
    except json.JSONDecodeError as error:
        raise RuntimeError("Superset SQL Lab returned malformed JSON results.") from error
    if not isinstance(result_payload, dict):
        raise TypeError("Superset SQL Lab returned an invalid result object.")

    return _query_rows(result_payload, max_rows, elapsed_ms)


def _require_single_select(sql: str, database: Database) -> None:
    if "{{" in sql or "{%" in sql:
        raise ValueError("Jinja templates are not allowed in Text to BI queries.")
    try:
        script = SQLScript(sql, engine=database.db_engine_spec.engine)
    except SupersetParseError:
        raise ValueError("SQL must be a valid read-only SELECT statement.") from None
    if len(script.statements) != 1 or script.has_mutation() or not script.statements[0].is_select():
        raise ValueError("Only one read-only SELECT statement is allowed.")


def _query_rows(payload: dict[str, Any], max_rows: int, elapsed_ms: int) -> QueryRows:
    column_payload = payload.get("columns")
    data_payload = payload.get("data")
    if not isinstance(column_payload, list) or not isinstance(data_payload, list):
        raise TypeError("Superset SQL Lab result must include columns and data arrays.")

    columns = [_column_name(column) for column in column_payload]
    if any(not name for name in columns) or len(set(columns)) != len(columns):
        raise RuntimeError("Superset SQL Lab returned invalid or duplicate column names.")

    rows: list[tuple[Any, ...]] = []
    for row in data_payload:
        if isinstance(row, dict):
            if any(column not in row for column in columns):
                raise RuntimeError("Superset SQL Lab row does not match the returned columns.")
            rows.append(tuple(row[column] for column in columns))
        elif isinstance(row, (list, tuple)) and len(row) == len(columns):
            rows.append(tuple(row))
        else:
            raise RuntimeError("Superset SQL Lab returned an unsupported row format.")

    return QueryRows(
        columns=columns,
        rows=rows[:max_rows],
        truncated=len(rows) > max_rows,
        elapsed_ms=elapsed_ms,
    )


def _column_name(column: Any) -> str:
    if isinstance(column, str):
        return column
    if isinstance(column, dict):
        name = column.get("column_name") or column.get("name")
        if isinstance(name, str):
            return name
    return ""
