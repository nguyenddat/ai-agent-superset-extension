import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.agent_package.tool_agent import ToolError
from text_to_bi.superset_text_to_bi.modules.expert_rule_management.services import ExpertRuleService

from .catalog_context import load_context

MAX_SUGGESTIONS = 8


def normalized(value: str) -> str:
    folded = unicodedata.normalize("NFD", value.casefold().replace("Ä‘", "d"))
    return " ".join("".join(char for char in folded if unicodedata.category(char) != "Mn").split())


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    label: str
    description: str | None
    synonyms: tuple[str, ...]
    contains_pii: bool
    unit: str | None = None
    format: str | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name, "data_type": self.data_type, "label": self.label, "description": self.description,
            "synonyms": list(self.synonyms), "contains_pii": self.contains_pii, "unit": self.unit,
            "format": self.format,
        }


@dataclass(frozen=True)
class TableInfo:
    id: int
    schema: str
    name: str
    label: str
    description: str | None
    grain: str | None
    columns: tuple[ColumnInfo, ...]

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    def column(self, reference: str) -> ColumnInfo:
        key = normalized(reference)
        for column in self.columns:
            if key in (column.name.lower(), normalized(column.label), *(normalized(item) for item in column.synonyms)):
                return column
        names = ", ".join(column.name for column in self.columns)
        raise ToolError(
            f"Cá»™t '{reference}' khÃ´ng thuá»™c báº£ng {self.qualified_name}. "
            f"CÃ¡c cá»™t há»£p lá»‡: {names}."
        )


@dataclass(frozen=True)
class MetricInfo:
    id: str
    name: str
    label: str | None
    expression: str
    description: str | None
    format: str | None
    currency: str | None
    warning_text: str | None
    table_id: int
    source_sql: str | None


@dataclass(frozen=True)
class RuleCondition:
    column: str
    operator: str
    value: Any


@dataclass(frozen=True)
class RuleInfo:
    id: UUID
    name: str
    table_id: int
    description: str | None
    conditions: tuple[RuleCondition, ...]
    exceptions: tuple[dict[str, str], ...]
    examples: tuple[dict[str, str], ...]
    metric_ids: frozenset[str]

    def describe(self, table: TableInfo | None) -> dict[str, Any]:
        return {
            "name": self.name, "table": table.qualified_name if table else None, "description": self.description,
            "conditions": [
                {"column": item.column, "operator": item.operator, "value": item.value} for item in self.conditions
            ],
            "exceptions": list(self.exceptions), "examples": list(self.examples),
        }


@dataclass
class AgentCatalog:
    tables: dict[int, TableInfo]
    metrics: dict[str, MetricInfo]
    rules: list[RuleInfo]
    table_names: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        short_names: dict[str, list[str]] = {}
        for table in self.tables.values():
            self.table_names[table.qualified_name.lower()] = table.qualified_name
            short_names.setdefault(table.name.lower(), []).append(table.qualified_name)
        for name, qualified in short_names.items():
            if len(qualified) == 1:
                self.table_names.setdefault(name, qualified[0])

    def table(self, reference: str) -> TableInfo:
        return _find(reference, self.tables.values(), lambda item: (
            str(item.id), item.qualified_name.lower(), item.name.lower(), normalized(item.label),
        ), "báº£ng", lambda item: item.qualified_name)

    def metric(self, reference: str) -> MetricInfo:
        return _find(reference, self.metrics.values(), lambda item: (
            str(item.id), item.name.lower(), normalized(item.label or item.name),
        ), "metric", lambda item: item.name)

    def rule(self, reference: str) -> RuleInfo:
        return _find(reference, self.rules, lambda item: (str(item.id), normalized(item.name)), "quy táº¯c",
                     lambda item: item.name)

    def metric_rules(self, metric_id: str) -> list[RuleInfo]:
        return [rule for rule in self.rules if metric_id in rule.metric_ids]

    def table_metrics(self, table_id: int) -> list[MetricInfo]:
        return [metric for metric in self.metrics.values() if metric.table_id == table_id]


Entry = TypeVar("Entry")


def _find(reference: str, entries: Iterable[Entry], keys: Any, kind: str, label: Any) -> Entry:
    wanted = reference.strip()
    candidates = list(entries)
    matches = [entry for entry in candidates if wanted.lower() in keys(entry) or normalized(wanted) in keys(entry)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ToolError(f"'{reference}' khá»›p nhiá»u {kind}: {', '.join(label(item) for item in matches)}. DÃ¹ng id.")
    query = normalized(wanted)
    similar = [label(entry) for entry in candidates if any(query in key or key in query for key in keys(entry) if key)]
    hint = f" Gáº§n giá»‘ng: {', '.join(similar[:MAX_SUGGESTIONS])}." if similar else ""
    raise ToolError(f"KhÃ´ng tÃ¬m tháº¥y {kind} '{reference}'.{hint}")


def load_catalog(session: Session, database_id: int) -> AgentCatalog:
    context = load_context(session, database_id)
    columns_by_table: dict[int, list[ColumnInfo]] = {}
    column_names: dict[int, str] = {}
    for entry in context.columns:
        dictionary = entry.dictionary
        column_names[entry.column.id] = entry.column.column_name
        columns_by_table.setdefault(entry.column.table_id, []).append(ColumnInfo(
            name=entry.column.column_name, data_type=entry.column.type, label=entry.label,
            description=(dictionary.description if dictionary else None) or entry.column.description,
            synonyms=tuple(entry.synonyms), contains_pii=bool(dictionary and dictionary.contains_pii),
            unit=(dictionary.unit if dictionary else None) or None,
            format=(dictionary.format if dictionary else None) or None,
        ))
    tables = {
        table_id: TableInfo(
            id=table_id, schema=entry.table.schema or "", name=entry.table.table_name, label=entry.label,
            description=(entry.dictionary.description if entry.dictionary else None) or entry.table.description,
            grain=entry.dictionary.grain_description if entry.dictionary else None,
            columns=tuple(columns_by_table.get(table_id, [])),
        )
        for table_id, entry in context.tables.items()
    }
    metrics = {
        str(metric.id): MetricInfo(
            id=str(metric.id), name=metric.name, label=metric.label, expression=metric.expression,
            description=metric.description, format=metric.format, currency=metric.currency,
            warning_text=metric.warning_text, table_id=metric.dataset_id, source_sql=None,
        )
        for metric in context.metrics
    }
    rule_service = ExpertRuleService(session)
    rules = [
        RuleInfo(
            id=rule["id"], name=rule["name"], table_id=dataset_id, description=rule["description"],
            conditions=tuple(
                RuleCondition(column=item["column_name"], operator=item["operator"], value=item.get("value"))
                for item in rule["conditions"]
            ),
            exceptions=tuple(rule["exceptions"] or ()), examples=tuple(rule["examples"] or ()),
            metric_ids=frozenset(
                reference["target_key"] for reference in rule["metric_refs"]
                if reference["kind"] == "metric"
            ),
        )
        for dataset_id in context.tables
        for rule in rule_service.discovery(dataset_id)
    ]
    return AgentCatalog(tables=tables, metrics=metrics, rules=rules)
