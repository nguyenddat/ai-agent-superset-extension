import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError

from text_to_bi.superset_text_to_bi.core.config import settings as config
from text_to_bi.superset_text_to_bi.modules.expert_rule_management.services import ExpertRuleService
from text_to_bi.superset_text_to_bi.modules.glossary_management.models import GlossaryTerm
from text_to_bi.superset_text_to_bi.modules.glossary_management.services import GlossaryService
from text_to_bi.superset_text_to_bi.modules.management_domains import DomainAssignment
from text_to_bi.superset_text_to_bi.modules.metric_management.models import metric_domains
from text_to_bi.superset_text_to_bi.modules.own_knowledge.models import OwnKnowledgeEntry
from text_to_bi.superset_text_to_bi.modules.own_knowledge.services import OwnKnowledgeService

from ..utils.topics import COLUMN, EXPERT_RULE, GLOSSARY, METRIC, OWN_KNOWLEDGE, TABLE
from .catalog_context import CatalogContext

OPERATOR_LABELS = {
    "equals": "bằng", "not_equals": "khác", "contains": "chứa", "not_contains": "không chứa",
    "greater_than": "lớn hơn", "greater_than_or_equal": "từ ... trở lên", "less_than": "nhỏ hơn",
    "less_than_or_equal": "từ ... trở xuống", "in": "là một trong", "not_in": "không thuộc",
    "is_null": "để trống", "is_not_null": "có giá trị",
}

KIND_LABELS = {"glossary": "thuật ngữ", "metric": "metric", "expert_rule": "quy tắc"}


@dataclass(frozen=True)
class IndexDocument:
    point_id: str
    topic: str
    entity_id: str
    database_id: int
    table_id: int | None
    text: str
    content_hash: str
    payload: dict[str, object]


DocumentBuilder = Callable[[Session, CatalogContext], list[IndexDocument]]


def build_document(
    topic: str, entity_id: UUID | int | str, database_id: int, table_id: int | None, text: str, **fields: object
) -> IndexDocument:
    clean_text = " ".join(text.split())
    payload: dict[str, object] = {
        "topic": topic,
        "entity_id": str(entity_id),
        "database_id": str(database_id),
        "dataset_id": str(table_id) if table_id is not None else None,
        "table_id": str(table_id) if table_id is not None else None,
        "text": clean_text,
        "model_version": config.text2sql_embedding_model,
        "embedding_dimensions": config.text2sql_embedding_dimensions,
        **fields,
    }
    content_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    payload["content_hash"] = content_hash
    return IndexDocument(
        point_id=str(uuid5(NAMESPACE_URL, f"text2sql:{topic}:{entity_id}")),
        topic=topic,
        entity_id=str(entity_id),
        database_id=database_id,
        table_id=table_id,
        text=clean_text,
        content_hash=content_hash,
        payload=payload,
    )


def build_table_documents(session: Session, context: CatalogContext) -> list[IndexDocument]:
    documents: list[IndexDocument] = []
    for entry in context.tables.values():
        dictionary = entry.dictionary
        text = " | ".join(filter(None, [
            f"Bảng: {entry.label}", f"Tên kỹ thuật: {entry.qualified_name}",
            f"Mô tả: {dictionary.description}" if dictionary and dictionary.description else None,
            f"Grain: {dictionary.grain_description}" if dictionary and dictionary.grain_description else None,
        ]))
        documents.append(build_document(
            TABLE, entry.table.id, context.database_id, entry.table.id, text,
            name=entry.table.table_name, display_name=entry.label,
        ))
    return documents


def build_column_documents(session: Session, context: CatalogContext) -> list[IndexDocument]:
    documents: list[IndexDocument] = []
    for entry in context.columns:
        column, dictionary = entry.column, entry.dictionary
        table = context.tables[column.table_id]
        text = " | ".join(filter(None, [
            f"Cột: {entry.label}", f"Tên kỹ thuật: {column.column_name}",
            f"Bảng: {table.label} ({table.qualified_name})",
            f"Mô tả: {dictionary.description}" if dictionary and dictionary.description else column.description,
            f"Thuật ngữ: {dictionary.business_term}" if dictionary and dictionary.business_term else None,
            f"Đồng nghĩa: {', '.join(entry.synonyms)}" if entry.synonyms else None,
            f"Đơn vị: {dictionary.unit}" if dictionary and dictionary.unit else None,
        ]))
        documents.append(build_document(
            COLUMN, column.id, context.database_id, column.table_id, text,
            name=column.column_name, display_name=entry.label,
        ))
    return documents


def referenced_columns(expression: str, columns_by_name: dict[str, int]) -> list[str]:
    try:
        parsed = parse_one(expression, read="postgres")
    except SqlglotError:
        return []
    if parsed is None:
        return []
    identifiers = {column.name.lower() for column in parsed.find_all(exp.Column)}
    return sorted(str(columns_by_name[name]) for name in identifiers if name in columns_by_name)


def build_metric_documents(session: Session, context: CatalogContext) -> list[IndexDocument]:
    documents: list[IndexDocument] = []
    domains = DomainAssignment(session, metric_domains, "metric_id")
    for metric in context.metrics:
        table = context.tables[metric.dataset_id]
        referenced = referenced_columns(metric.expression, context.columns_by_table.get(table.table.id, {}))
        column_labels = [context.column_label(int(value)) for value in referenced]
        metric_domains_for_row = domains.read_one(metric.id)
        text = " | ".join(filter(None, [
            f"Metric: {metric.label or metric.name}", f"Tên kỹ thuật: {metric.name}",
            f"Mô tả: {metric.description}" if metric.description else None,
            f"Miền nghiệp vụ: {', '.join(domain['name'] for domain in metric_domains_for_row)}"
            if metric_domains_for_row else None,
            f"Bảng: {table.label} ({table.qualified_name})",
            f"Cột liên quan: {', '.join(filter(None, column_labels))}" if referenced else None,
        ]))
        documents.append(build_document(
            METRIC, metric.id, context.database_id, table.table.id, text, name=metric.name,
            display_name=metric.label or metric.name, origin="manual", is_active=True,
            column_ids=referenced,
        ))
    return documents


def _link_text(context: CatalogContext, kind: str, target_key: str, dataset_id: int) -> str | None:
    if kind == "table":
        label = context.table_label(int(target_key))
        return f"Table {label}" if label else None
    if kind == "column":
        for entry in context.columns:
            if entry.column.table_id == dataset_id and entry.column.column_name == target_key:
                table_label = context.table_label(entry.column.table_id)
                return f"Column {entry.label} (table {table_label})" if table_label else f"Column {entry.label}"
        return None
    if kind == "metric":
        try:
            label = context.metric_label(UUID(target_key))
        except ValueError:
            label = target_key
        return f"Metric {label}" if label else None
    return target_key


def build_glossary_documents(session: Session, context: CatalogContext) -> list[IndexDocument]:
    documents: list[IndexDocument] = []
    for term in [
        term for dataset_id in context.tables
        for term in GlossaryService(session).discovery(dataset_id)
    ]:
        dataset_id = term["dataset_id"]
        links: dict[str, list[str]] = {"table": [], "column": [], "metric": [], "superset_metric": []}
        link_texts: list[str] = []
        for link in term["links"]:
            target_id = str(link["target_key"])
            text = _link_text(context, link["kind"], target_id, dataset_id)
            if text is not None:
                links[link["kind"]].append(target_id)
                link_texts.append(text)
        synonyms = term["synonyms"]
        text = " | ".join(filter(None, [
            f"Thuật ngữ: {term['name']}", f"Định nghĩa: {term['definition']}",
            f"Miền nghiệp vụ: {', '.join(domain['name'] for domain in term['business_domains'])}"
            if term["business_domains"] else None,
            f"Đồng nghĩa: {', '.join(synonyms)}" if synonyms else None,
            f"Liên quan: {'; '.join(link_texts)}" if link_texts else None,
        ]))
        documents.append(build_document(
            GLOSSARY, term["id"], context.database_id, dataset_id, text, name=term["name"],
            display_name=term["name"],
            synonyms=list(synonyms), table_ids=sorted(links["table"]), column_ids=sorted(links["column"]),
            metric_ids=sorted(links["metric"]), superset_metric_ids=sorted(links["superset_metric"]),
        ))
    return documents


def condition_text(context: CatalogContext, dataset_id: int, condition: dict[str, Any]) -> str:
    column_name = condition["column_name"]
    column_id = context.columns_by_table.get(dataset_id, {}).get(column_name.lower())
    column = context.column_label(column_id) if column_id is not None else column_name
    operator = OPERATOR_LABELS.get(condition["operator"], condition["operator"])
    value = condition.get("value")
    if condition["operator"] in ("is_null", "is_not_null") or value is None:
        return f"{column} {operator}"
    rendered = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
    return f"{column} {operator} {rendered}"


def build_expert_rule_documents(session: Session, context: CatalogContext) -> list[IndexDocument]:
    rules = [
        rule for dataset_id in context.tables
        for rule in ExpertRuleService(session).discovery(dataset_id)
    ]
    term_ids = {term_id for rule in rules for term_id in rule["glossary_term_ids"]}
    term_names = {
        term.id: term.canonical_name
        for term in session.scalars(select(GlossaryTerm).where(GlossaryTerm.id.in_(term_ids)))
    } if term_ids else {}
    documents: list[IndexDocument] = []
    for rule in rules:
        dataset_id = rule["dataset_id"]
        table_label = context.table_label(dataset_id)
        conditions = [condition_text(context, dataset_id, condition) for condition in rule["conditions"]]
        exceptions = [f"khi {item['when']} thì {item['outcome']}" for item in rule["exceptions"]]
        examples = [f"\"{item['question']}\" → {item['intent']}" for item in rule["examples"]]
        terms = [term_names[term_id] for term_id in rule["glossary_term_ids"] if term_id in term_names]
        metrics = []
        for item in rule["metric_refs"]:
            target_key = item["target_key"]
            if item["kind"] == "metric":
                try:
                    target_key = context.metric_label(UUID(target_key)) or target_key
                except ValueError:
                    pass
            metrics.append(target_key)
        text = " | ".join(filter(None, [
            f"Quy tắc: {rule['name']}",
            f"Miền nghiệp vụ: {', '.join(domain['name'] for domain in rule['business_domains'])}"
            if rule["business_domains"] else None,
            f"Bảng: {table_label}" if table_label else None,
            f"Mô tả: {rule['description']}" if rule["description"] else None,
            f"Điều kiện: {'; '.join(conditions)}" if conditions else None,
            f"Ngoại lệ: {'; '.join(exceptions)}" if exceptions else None,
            f"Ví dụ: {'; '.join(examples)}" if examples else None,
            f"Thuật ngữ: {', '.join(terms)}" if terms else None,
            f"Metric: {', '.join(metrics)}" if metrics else None,
        ]))
        documents.append(build_document(
            EXPERT_RULE, rule["id"], context.database_id, dataset_id, text, name=rule["name"],
            display_name=rule["name"], glossary_term_ids=sorted(str(item) for item in rule["glossary_term_ids"]),
            metric_refs=rule["metric_refs"],
        ))
    return documents


def build_own_knowledge_documents(session: Session, context: CatalogContext) -> list[IndexDocument]:
    documents: list[IndexDocument] = []
    knowledge_service = OwnKnowledgeService(session)
    for dataset_id in context.tables:
        entries = session.scalars(
            select(OwnKnowledgeEntry)
            .where(OwnKnowledgeEntry.dataset_id == dataset_id)
            .order_by(OwnKnowledgeEntry.name, OwnKnowledgeEntry.id)
        )
        for row in entries:
            if not knowledge_service._active_for_agent(row):
                continue
            entry = knowledge_service._entry(row)
            table_label = context.table_label(entry["dataset_id"])
            text = " | ".join(filter(None, [
                f"Own knowledge: {entry['name']}", f"Kind: {KIND_LABELS.get(entry['kind'], entry['kind'])}",
                f"Definition: {entry['definition']}",
                f"Table: {table_label}" if table_label else None,
            ]))
            documents.append(build_document(
                OWN_KNOWLEDGE, entry["id"], context.database_id, entry["dataset_id"], text, name=entry["name"],
                display_name=entry["name"], user_id=str(entry["user_id"]), kind=entry["kind"],
            ))
    return documents


TOPIC_BUILDERS: dict[str, DocumentBuilder] = {
    TABLE: build_table_documents,
    COLUMN: build_column_documents,
    METRIC: build_metric_documents,
    GLOSSARY: build_glossary_documents,
    EXPERT_RULE: build_expert_rule_documents,
    OWN_KNOWLEDGE: build_own_knowledge_documents,
}
