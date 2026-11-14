import hashlib
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from text_to_bi.superset_semantic_layer.modules.metric_management.schemas.status_enum import ContractOrigin
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_formula import (
    parse_contract_metric,
)
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_validation import (
    METRIC_CONTRACT_RULE,
    metric_contract_ineligibility,
)

from ..exceptions import DatasetDraftValidationError

AGENT_ORIGIN = ContractOrigin.AI_AGENT.value
AGGREGATE_DATASET = "aggregate"
BASE_DATASET = "base"
AGENT_DATASET_TYPES = (AGGREGATE_DATASET, BASE_DATASET)
# An unattended agent must not flood a dataset with candidates nobody has reviewed yet.
MAX_PENDING_AGENT_METRICS = 50
METRIC_NAME_MAX_LENGTH = 100
METRIC_LABEL_MAX_LENGTH = 150
METRIC_DEFINITION_MAX_LENGTH = 1_000
METRIC_UNIT_MAX_LENGTH = 64
QUESTION_MAX_LENGTH = 1_000
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class AgentMetricDraft:
    metric_name: str
    label: str
    expression: str
    definition: str
    unit: str | None


def _text(body: dict[str, Any], key: str, limit: int, required: bool = True) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value.strip()) > limit:
        raise DatasetDraftValidationError(
            f"{key} phải là văn bản{' không rỗng' if required else ''}, tối đa {limit} ký tự."
        )
    return value.strip() or None


def checked_metric_draft(body: dict[str, Any], dataset: Any) -> AgentMetricDraft:
    """The agent's metric, held to the same formula rule as any contract metric on this dataset."""
    metric_name = _text(body, "metric_name", METRIC_NAME_MAX_LENGTH).lower()
    if not _IDENTIFIER.fullmatch(metric_name):
        raise DatasetDraftValidationError("Tên metric chỉ được gồm chữ cái thường không dấu, chữ số và dấu gạch dưới.")
    expression = _text(body, "expression", 2_000)
    if parse_contract_metric(expression) is None:
        raise DatasetDraftValidationError(METRIC_CONTRACT_RULE)
    proposed = SimpleNamespace(metric_name=metric_name, expression=expression)
    if ineligibility := metric_contract_ineligibility(dataset, proposed):
        raise DatasetDraftValidationError(ineligibility)
    return AgentMetricDraft(
        metric_name=metric_name,
        label=_text(body, "label", METRIC_LABEL_MAX_LENGTH),
        expression=expression,
        definition=_text(body, "definition", METRIC_DEFINITION_MAX_LENGTH),
        unit=_text(body, "unit", METRIC_UNIT_MAX_LENGTH, required=False),
    )


def asked_question(body: dict[str, Any]) -> str | None:
    """The question that made the agent build a metric, kept in the review history; optional."""
    return _text(body, "question", QUESTION_MAX_LENGTH, required=False)


def normalized_formula(expression: str) -> str | None:
    """A formula written the same way whatever its spacing, keyword case or quoting; None when it does not parse.

    A quoted lowercase name is the same column as the unquoted one in PostgreSQL, so its quotes are dropped.
    """
    try:
        tree = sqlglot.parse_one(expression)
    except SqlglotError:
        return None
    for identifier in tree.find_all(exp.Identifier):
        if identifier.name == identifier.name.lower():
            identifier.set("quoted", False)
    return tree.sql(dialect="postgres", normalize=True)




def matching_metric(dataset: Any, expression: str) -> Any | None:
    """A metric already on the dataset with the same formula, so the agent reuses it instead of adding a copy."""
    wanted = normalized_formula(expression)
    return next(
        (
            metric for metric in getattr(dataset, "metrics", [])
            if wanted is not None and normalized_formula(str(metric.expression or "")) == wanted
        ),
        None,
    )


def unique_metric_name(dataset: Any, metric_name: str) -> str:
    taken = {str(metric.metric_name) for metric in getattr(dataset, "metrics", [])}
    candidate, suffix = metric_name, 2
    while candidate in taken:
        candidate, suffix = f"{metric_name}_{suffix}", suffix + 1
    return candidate




DATASET_NAME_MAX_LENGTH = 100
DATASET_SQL_MAX_LENGTH = 20_000
# Statements and clauses that write, change the schema or reach outside one read-only query.
_WRITING_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command, exp.Merge, exp.Into)
# Server functions that read files, settings or other databases, or take locks; a dataset never needs them.
_SERVER_FUNCTION_PREFIXES = ("pg_", "dblink", "lo_", "current_setting", "set_config", "query_to_xml", "txid_")


@dataclass(frozen=True)
class CheckedDatasetSql:
    sql: str
    output_columns: list[str]
    source_datasets: list[Any]


def checked_dataset_sql(sql: Any, allowed_datasets: dict[str, Any]) -> CheckedDatasetSql:
    """A single read-only SELECT over the allowed base datasets, keyed by table name, with named output columns."""
    if not isinstance(sql, str) or not sql.strip() or len(sql) > DATASET_SQL_MAX_LENGTH:
        raise DatasetDraftValidationError(f"SQL phải là văn bản không rỗng, tối đa {DATASET_SQL_MAX_LENGTH} ký tự.")
    try:
        statements = [statement for statement in sqlglot.parse(sql, read="postgres") if statement is not None]
    except SqlglotError as ex:
        raise DatasetDraftValidationError("Không đọc được câu SQL.") from ex
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise DatasetDraftValidationError("SQL phải là đúng một câu SELECT.")
    tree = statements[0]
    if any(isinstance(node, _WRITING_NODES) for node in tree.walk()):
        raise DatasetDraftValidationError("SQL chỉ được đọc dữ liệu.")
    if any(isinstance(node, exp.CTE) for node in tree.walk()):
        raise DatasetDraftValidationError("SQL không được dùng WITH trong đề xuất dataset.")
    for function in tree.find_all(exp.Func):
        name = (function.name if isinstance(function, exp.Anonymous) else function.sql_name()).lower()
        if name.startswith(_SERVER_FUNCTION_PREFIXES):
            raise DatasetDraftValidationError(f"Không được dùng hàm {name}.")
    sources: dict[int, Any] = {}
    for table in tree.find_all(exp.Table):
        dataset = allowed_datasets.get(table.name)
        if dataset is None or table.catalog or (table.db and table.db != (getattr(dataset, "schema", None) or "")):
            raise DatasetDraftValidationError(f"{table.sql(dialect='postgres')} không phải dataset cơ sở bạn được dùng.")
        sources[dataset.id] = dataset
    if not sources:
        raise DatasetDraftValidationError("SQL phải đọc ít nhất một dataset cơ sở.")
    output_columns = []
    for selected in tree.expressions:
        if isinstance(selected, exp.Star) or isinstance(getattr(selected, "this", None), exp.Star):
            raise DatasetDraftValidationError("Liệt kê rõ từng cột kết quả, không dùng *.")
        name = selected.alias_or_name
        if not _IDENTIFIER.fullmatch(name or ""):
            raise DatasetDraftValidationError(
                f"Cột kết quả {selected.sql(dialect='postgres')} cần tên chữ thường không dấu."
            )
        output_columns.append(name)
    if len(set(output_columns)) != len(output_columns):
        raise DatasetDraftValidationError("Tên cột kết quả bị trùng.")
    return CheckedDatasetSql(tree.sql(dialect="postgres", pretty=True), output_columns, list(sources.values()))


@dataclass(frozen=True)
class DerivedColumnKeys:
    """Key flags of an output column, and the base column (dataset ID, column name) it reads and references."""

    is_pk: bool
    is_unique: bool
    referenced: tuple[int, str]


def _is_key(entry: Any) -> bool:
    return any(getattr(entry, flag, False) for flag in ("is_pk", "is_fk", "is_unique"))


def _joins_to_one(tree: exp.Select, aliases: dict[str, Any], entries: dict[int, dict[str, Any]]) -> bool:
    """Whether every join matches at most one row: its ON clause equates a unique column of the joined table."""
    pk_counts = {
        dataset_id: sum(1 for entry in columns.values() if getattr(entry, "is_pk", False))
        for dataset_id, columns in entries.items()
    }
    for join in tree.args.get("joins") or []:
        joined = join.this
        dataset = aliases.get(joined.alias_or_name) if isinstance(joined, exp.Table) else None
        if dataset is None or join.args.get("on") is None:
            return False
        unique_sides = [
            column
            for equality in join.args["on"].find_all(exp.EQ)
            for column in (equality.left, equality.right)
            if isinstance(column, exp.Column)
            and column.table == joined.alias_or_name
            and (
                getattr(entries.get(dataset.id, {}).get(column.name), "is_unique", False)
                or (
                    getattr(entries.get(dataset.id, {}).get(column.name), "is_pk", False) and pk_counts[dataset.id] == 1
                )
            )
        ]
        if not unique_sides:
            return False
    return True


def derived_column_keys(
    sql: str,
    source_datasets: list[Any],
    entries: dict[int, dict[str, Any]],
) -> dict[str, DerivedColumnKeys]:
    """Data dictionary keys of a proposed dataset's output columns, carried over from the base columns they read.

    Like the existing fact datasets, an output column that reads a key column of a base dataset unchanged is a foreign
    key to that base column, which is what draws the lineage edge between them; an attribute or a computed column gets
    no key. It stays a primary key or unique only while the query keeps the base table's rows one to one: it is read
    from the FROM table, nothing is grouped or made distinct, and every join matches at most one row. `entries` maps
    a source dataset ID to its column dictionary rows by column name.
    """
    tree = sqlglot.parse_one(sql, read="postgres")
    if not isinstance(tree, exp.Select) or tree.args.get("with"):
        return {}
    by_name = {str(dataset.table_name): dataset for dataset in source_datasets}
    aliases = {table.alias_or_name: by_name[table.name] for table in tree.find_all(exp.Table) if table.name in by_name}
    source = tree.args.get("from_")
    from_table = source.this if source is not None else None
    from_alias = from_table.alias_or_name if isinstance(from_table, exp.Table) else None
    keeps_rows = not tree.args.get("group") and not tree.args.get("distinct") and _joins_to_one(tree, aliases, entries)
    derived = {}
    for selected in tree.expressions:
        column = selected.unalias()
        if not isinstance(column, exp.Column):
            continue
        if column.table:
            alias = column.table
        else:
            # An unqualified column belongs to the one source table that has it.
            owners = [name for name, dataset in aliases.items() if column.name in entries.get(dataset.id, {})]
            alias = owners[0] if len(owners) == 1 else None
        dataset = aliases.get(alias)
        entry = entries.get(dataset.id, {}).get(column.name) if dataset is not None else None
        if not _is_key(entry):
            continue
        row_preserving = keeps_rows and alias == from_alias
        derived[selected.alias_or_name] = DerivedColumnKeys(
            is_pk=row_preserving and bool(entry.is_pk),
            is_unique=row_preserving and bool(entry.is_unique),
            referenced=(dataset.id, column.name),
        )
    return derived


def sql_fingerprint(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def checked_dataset_proposal(body: Any, allowed_datasets: dict[str, Any]) -> dict[str, Any]:
    """The agent's dataset: a name, its SQL over base datasets and the metric the question needs on its columns."""
    if not isinstance(body, dict):
        raise DatasetDraftValidationError("A JSON object is required.")
    name = _text(body, "name", DATASET_NAME_MAX_LENGTH).lower()
    if not _IDENTIFIER.fullmatch(name):
        raise DatasetDraftValidationError("Tên dataset chỉ được gồm chữ cái thường không dấu, chữ số và dấu gạch dưới.")
    checked = checked_dataset_sql(body.get("sql"), allowed_datasets)
    if len({getattr(dataset, "database_id", None) for dataset in checked.source_datasets}) != 1:
        raise DatasetDraftValidationError("Các dataset nguồn phải cùng một kết nối cơ sở dữ liệu.")
    metric = body.get("metric")
    if not isinstance(metric, dict):
        raise DatasetDraftValidationError("Cần metric trên dataset mới.")
    output = SimpleNamespace(
        sql=None,
        columns=[
            SimpleNamespace(column_name=column, is_active=True, expression=None) for column in checked.output_columns
        ],
    )
    draft = checked_metric_draft(metric, output)
    first_source = checked.source_datasets[0]
    return {
        "name": name,
        "label": _text(body, "label", METRIC_LABEL_MAX_LENGTH),
        "description": _text(body, "description", METRIC_DEFINITION_MAX_LENGTH, required=False),
        "sql": checked.sql,
        "sql_fingerprint": sql_fingerprint(checked.sql),
        "database_id": first_source.database_id,
        "schema": getattr(first_source, "schema", None),
        "metric": {
            "metric_name": draft.metric_name,
            "label": draft.label,
            "expression": draft.expression,
            "definition": draft.definition,
            "unit": draft.unit,
        },
        "source_dataset_ids": sorted(dataset.id for dataset in checked.source_datasets),
        "question": asked_question(body),
    }
