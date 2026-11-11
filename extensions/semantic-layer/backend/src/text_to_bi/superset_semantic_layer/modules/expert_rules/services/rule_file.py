from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ....common.exceptions import SemanticLayerError
from ....common.utils.table_file import (
    ImportRow,
    dataset_named,
    join_list,
    read_table,
    refusal_message,
    split_list,
    write_table,
)
from ..exceptions import ExpertRuleValidationError
from .expert_rule import (
    _CONDITION_OPERATORS,
    create_draft,
    normalize_rule_payload,
    update_draft,
    validate_semantic_links,
)
from .expert_rule_group import create_rule_group, move_rule, normalize_group_payload

RULE_HEADERS = ("name", "dataset", "group", "glossary_terms", "conditions", "exceptions", "examples")
REQUIRED_RULE_HEADERS = ("name", "dataset", "glossary_terms", "conditions", "examples")
RULE_FILE_NAME = "expert-rule"
CONDITION_SEPARATOR = "|"
PAIR_SEPARATOR = "=>"
# The editor's validation answers in English; the preview shows these in Vietnamese.
RULE_MESSAGES = {
    "An expert rule needs at least one approved glossary term.": "Rule cần ít nhất một thuật ngữ đã duyệt.",
    "Invalid glossary link.": "Thuật ngữ phải đã được duyệt và có liên kết tới dataset của rule.",
    "Invalid metric link.": "Metric của thuật ngữ phải đã được duyệt và thuộc dataset của rule.",
    "Invalid condition field reference.": "Cột trong điều kiện không thuộc Data Dictionary của dataset.",
    "Invalid conditions.": "Điều kiện không hợp lệ: kiểm tra giá trị (is_null, is_not_null không có giá trị).",
    "Invalid legacy conditions.": "Điều kiện không hợp lệ.",
    "Invalid examples.": "Cần từ 1 đến 50 câu hỏi ví dụ.",
    "Invalid exceptions.": "Có tối đa 50 ngoại lệ.",
    "Could not save the expert rule.": "Không lưu được rule.",
}
FIELD_LABELS = {
    "name": "Tên rule",
    "exceptions.when": "Ngoại lệ (khi nào)",
    "exceptions.outcome": "Ngoại lệ (kết quả)",
    "examples.question": "Câu hỏi ví dụ",
    "examples.intent": "Cách hiểu câu hỏi",
}


@dataclass(frozen=True)
class RuleReferences:
    """What a rule file names, resolved as ExpertRuleAPI's editor resolves it.

    `datasets` holds the business datasets by table name. The callables are the API's own: a dataset, a serving
    glossary term or an approved metric by ID, a link's fingerprint, a dataset's Data Dictionary column resolver
    (by column name or ID), and the payload completed with the metrics its glossary terms name.
    """

    datasets: dict[str, list[Any]]
    dataset: Callable[[int], Any]
    glossary: Callable[[int], Any]
    metric: Callable[[int], Any]
    fingerprint: Callable[[str, int, int], Any]
    column_resolver: Callable[[int], Callable[[Any], Any]]
    term_metrics: Callable[[dict[str, Any]], dict[str, Any]]

    def editor_resolvers(self, dataset_id: int) -> tuple:
        """The resolvers `create_draft` and `update_draft` take after the actor."""
        return self.dataset, self.glossary, self.metric, self.fingerprint, self.column_resolver(dataset_id)


@dataclass
class RulePlan:
    """How a row is applied: the editor payload, the rule it updates and the group the import creates for it."""

    payload: dict[str, Any]
    rule_id: int | None = None
    revision: Any = None
    content_changed: bool = True
    new_group: str | None = None


def export_rules(session: Any, references: RuleReferences, file_format: str) -> dict[str, str]:
    """Every rule's current revision as a CSV or XLSX file that the import reads back unchanged."""
    from ..repositories.expert_rule import ExpertRuleRepository
    from ..repositories.expert_rule_link import ExpertRuleLinkRepository
    from ..repositories.expert_rule_revision import ExpertRuleRevisionRepository

    rule_repository, link_repository = ExpertRuleRepository(session), ExpertRuleLinkRepository(session)
    terms = _term_repository(session)
    rows = []
    for revision in ExpertRuleRevisionRepository(session).current():
        rule = rule_repository.get(revision.rule_id)
        dataset = references.dataset(rule.dataset_id)
        column = references.column_resolver(rule.dataset_id)
        term_ids = [link.target_id for link in link_repository.for_revision(revision.id) if link.kind == "glossary"]
        rows.append(
            [
                revision.name,
                dataset.table_name if dataset else f"#{rule.dataset_id}",
                rule.group.name if rule.group else "",
                join_list(_term_name(terms.get(term_id), term_id) for term_id in sorted(term_ids)),
                "\n".join(_condition_line(condition, column) for condition in revision.conditions),
                "\n".join(f"{item['when']} {PAIR_SEPARATOR} {item['outcome']}" for item in revision.exceptions),
                "\n".join(f"{item['question']} {PAIR_SEPARATOR} {item['intent']}" for item in revision.examples),
            ]
        )
    rows.sort(key=lambda row: row[0].casefold())
    return write_table(RULE_HEADERS, rows, file_format, RULE_FILE_NAME, ExpertRuleValidationError)


def preview_rule_import(session: Any, payload: Any, references: RuleReferences) -> list[ImportRow]:
    """What importing each row of the file would do, checked as the editor checks a rule; nothing is saved."""
    first_rows: dict[str, int] = {}
    result = []
    for number, cells in read_table(payload, RULE_HEADERS, REQUIRED_RULE_HEADERS, ExpertRuleValidationError):
        item = ImportRow(row=number, key=cells["name"])
        name_key = " ".join(cells["name"].split()).casefold()
        try:
            if name_key and name_key in first_rows:
                raise ExpertRuleValidationError(f"Rule trùng tên với dòng {first_rows[name_key]}.")
            first_rows.setdefault(name_key, number)
            _plan_rule(session, item, cells, references)
        except SemanticLayerError as error:
            item.action, item.message, item.changes = "error", _rule_message(str(error)), []
        result.append(item)
    return result


def apply_rule_import(session: Any, payload: Any, references: RuleReferences, actor_id: int) -> list[ImportRow]:
    """Create and update the rules of a file through their review lifecycle; a file with a failing row saves nothing.

    A new rule and an edited one become drafts waiting for review, exactly as from the editor; an approved rule is
    never approved by the import. A row that only changes the group moves the rule without review. The caller commits
    once.
    """
    rows = preview_rule_import(session, payload, references)
    refusal = refusal_message(rows)
    if refusal:
        raise ExpertRuleValidationError(refusal)
    created_groups: dict[str, int] = {}
    for item in rows:
        plan = item.plan
        if item.action == "unchanged":
            continue
        rule_payload = dict(plan.payload)
        if plan.new_group is not None:
            group_key = plan.new_group.casefold()
            if group_key not in created_groups:
                created_groups[group_key] = create_rule_group(session, {"name": plan.new_group}).id
            rule_payload["group_id"] = created_groups[group_key]
        resolvers = references.editor_resolvers(rule_payload["dataset_id"])
        if plan.rule_id is None:
            create_draft(session, rule_payload, actor_id, *resolvers)
        elif plan.content_changed:
            update_draft(session, plan.revision, rule_payload, plan.revision.lifecycle_version, actor_id, *resolvers)
        else:
            move_rule(session, plan.rule_id, rule_payload["group_id"], actor_id)
    return rows


def _plan_rule(session: Any, item: ImportRow, cells: dict[str, str], references: RuleReferences) -> None:
    from ..repositories.expert_rule import ExpertRuleRepository
    from ..repositories.expert_rule_group import ExpertRuleGroupRepository
    from ..repositories.expert_rule_link import ExpertRuleLinkRepository
    from ..repositories.expert_rule_revision import ExpertRuleRevisionRepository

    dataset = dataset_named(cells["dataset"], references.datasets, ExpertRuleValidationError)
    rule = ExpertRuleRepository(session).by_normalized_name(" ".join(cells["name"].split()).casefold())
    revision = ExpertRuleRevisionRepository(session).current_for(rule.id) if rule else None
    if rule is not None and rule.dataset_id != dataset.id:
        raise ExpertRuleValidationError("Rule đã gắn với một dataset khác; không thể chuyển rule sang dataset khác.")
    column = references.column_resolver(dataset.id)
    terms = _term_repository(session)
    condition_lines = [line for line in cells["conditions"].splitlines() if line.strip()]
    rule_payload = references.term_metrics(
        {
            "schema_version": 1,
            "name": cells["name"],
            "dataset_id": dataset.id,
            "conditions": [_condition(line, column, dataset) for line in condition_lines],
            "exceptions": (
                _pairs(cells["exceptions"], "when", "outcome", "Ngoại lệ", "<khi nào> => <kết quả>")
                if "exceptions" in cells
                else list(revision.exceptions) if revision else []
            ),
            "examples": _pairs(cells["examples"], "question", "intent", "Ví dụ", "<câu hỏi> => <cách hiểu>"),
            "glossary_term_ids": [_term_id(terms, name) for name in split_list(cells["glossary_terms"])],
        }
    )
    values = normalize_rule_payload(rule_payload, column)
    validate_semantic_links(values, references.dataset, references.glossary, references.metric)
    plan = RulePlan(rule_payload)
    if "group" in cells:
        group = None
        if cells["group"]:
            group = ExpertRuleGroupRepository(session).by_normalized_name(" ".join(cells["group"].split()).casefold())
            if group is None:
                plan.new_group = normalize_group_payload({"name": cells["group"]})["name"]
        rule_payload["group_id"] = group.id if group else None
    item.plan = plan
    new_group_note = f" Tạo nhóm mới «{plan.new_group}»." if plan.new_group else ""
    if rule is None:
        item.action, item.message = "create", "Tạo rule mới, chờ duyệt." + new_group_note
        return
    if revision is None:
        raise ExpertRuleValidationError("Rule không có phiên bản hiện hành để sửa.")
    links = ExpertRuleLinkRepository(session).for_revision(revision.id)
    stored_terms = {link.target_id for link in links if link.kind == "glossary"}
    stored_metrics = {link.target_id for link in links if link.kind == "metric"}
    group_given = "group_id" in rule_payload
    group_changed = group_given and (plan.new_group is not None or rule_payload["group_id"] != rule.group_id)
    changes = [
        field
        for field, changed in (
            ("name", values["name"] != revision.name),
            ("conditions", values["conditions"] != revision.conditions),
            ("exceptions", values["exceptions"] != revision.exceptions),
            ("examples", values["examples"] != revision.examples),
            ("glossary_terms", set(values["glossary_term_ids"]) != stored_terms),
            ("metrics", set(values["metric_ids"]) != stored_metrics),
            ("group", group_changed),
        )
        if changed
    ]
    plan.rule_id, plan.revision = rule.id, revision
    plan.content_changed = any(field != "group" for field in changes)
    item.changes = changes
    if not changes:
        item.action = "unchanged"
    elif not plan.content_changed:
        item.action, item.message = "update", "Chỉ chuyển nhóm; trạng thái duyệt giữ nguyên." + new_group_note
    elif revision.status == "approved":
        item.action = "update"
        item.message = "Tạo bản nháp mới chờ duyệt; bản đã duyệt ngừng được dùng cho tới khi bản nháp được duyệt."
        item.message += new_group_note
    else:
        item.action, item.message = "update", "Tạo bản nháp mới chờ duyệt." + new_group_note


def _term_repository(session: Any) -> Any:
    from ...glossary.repositories.glossary_term import GlossaryTermRepository

    return GlossaryTermRepository(session)


def _term_id(terms: Any, name: str) -> int:
    term = terms.by_normalized_name(" ".join(name.split()).casefold())
    if term is None:
        raise ExpertRuleValidationError(f"Không có thuật ngữ «{name}».")
    return term.id


def _term_name(term: Any, term_id: int) -> str:
    return term.canonical_name if term else f"#{term_id}"


def _condition(line: str, column: Callable[[Any], Any], dataset: Any) -> dict[str, Any]:
    """A condition the editor's legacy form reads, from `<column> | <operator> | <value>`.

    The value is read as JSON when it parses (35, true, ["a", "b"], "35") and as text otherwise; it is empty for
    is_null and is_not_null.
    """
    parts = [part.strip() for part in line.split(CONDITION_SEPARATOR, 2)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ExpertRuleValidationError(f"Điều kiện «{line.strip()}» phải có dạng <cột> | <toán tử> | <giá trị>.")
    column_name, operator = parts[0], parts[1]
    if operator not in _CONDITION_OPERATORS:
        raise ExpertRuleValidationError(
            f"Toán tử «{operator}» không hợp lệ; dùng một trong: {', '.join(sorted(_CONDITION_OPERATORS))}."
        )
    if not column(column_name):
        raise ExpertRuleValidationError(
            f"Cột «{column_name}» không có trong Data Dictionary của dataset «{dataset.table_name}»."
        )
    return {"field": column_name, "operator": operator, "value": _condition_value(parts[2] if len(parts) > 2 else "")}


def _condition_value(text: str) -> Any:
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return text
    return text if isinstance(value, dict) else value


def _condition_line(condition: dict[str, Any], column: Callable[[Any], Any]) -> str:
    column_id = condition["field_ref"]["column_dictionary_id"]
    row = column(column_id)
    parts = [row.column_name if row is not None else f"#{column_id}", condition["operator"]]
    value = condition["value"]
    if isinstance(value, str) and value and not _parses_as_json(value):
        parts.append(value)
    elif value is not None:
        # Text that would read back as JSON (a number, true, a list) is quoted so it stays text.
        parts.append(json.dumps(value, ensure_ascii=False))
    return f" {CONDITION_SEPARATOR} ".join(parts)


def _parses_as_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _pairs(cell: str, first: str, second: str, label: str, shape: str) -> list[dict[str, str]]:
    """One `<first> => <second>` pair per line of the cell."""
    pairs = []
    for line in cell.splitlines():
        if not line.strip():
            continue
        left, separator, right = line.partition(PAIR_SEPARATOR)
        if not separator:
            raise ExpertRuleValidationError(f"{label} «{line.strip()}» phải có dạng {shape}.")
        pairs.append({first: left.strip(), second: right.strip()})
    return pairs


def _rule_message(text: str) -> str:
    if text in RULE_MESSAGES:
        return RULE_MESSAGES[text]
    sentences = (("Unsafe ", "{} chứa cú pháp SQL, đường dẫn hoặc thông tin bí mật."), ("Invalid ", "{} không hợp lệ."))
    for prefix, sentence in sentences:
        if text.startswith(prefix) and text.endswith("."):
            field = text[len(prefix):-1]
            return sentence.format(FIELD_LABELS.get(field, field))
    return text
