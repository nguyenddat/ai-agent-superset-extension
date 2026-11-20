import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from text_to_bi.superset_semantic_layer.common.exceptions import SemanticLayerError
from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.common.utils.table_file import (
    ImportRow,
    TemplateColumn,
    dataset_named,
    join_list,
    read_table,
    refusal_message,
    split_list,
    write_table,
    write_template,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.dependencies import glossary_term_repository
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import (
    business_datasets_by_name,
    get_dataset,
)

from ..dependencies import (
    expert_rule_group_repository,
    expert_rule_link_repository,
    expert_rule_repository,
    expert_rule_revision_repository,
)
from ..exceptions import ExpertRuleValidationError
from ..models import ExpertRuleRevision
from .srv_expert_rule import ExpertRuleService
from .srv_expert_rule_group import ExpertRuleGroupService
from .srv_expert_rule_link import column_resolver, validate_semantic_links, with_term_metrics
from .srv_expert_rule_validation import (
    CONDITION_OPERATORS,
    normalize_group_payload,
    normalize_rule_payload,
    normalized_name,
)

RULE_FILE_NAME = "expert-rule"
CONDITION_SEPARATOR = "|"
PAIR_SEPARATOR = "=>"
RULE_COLUMNS = (
    TemplateColumn("name", True, "Tên rule; khớp rule đã có không phân biệt hoa thường.", "Ngày nắng nóng"),
    TemplateColumn("dataset", True, "Tên bảng của dataset; không đổi được sau khi tạo rule.", "tb_gia_tri_quan_sat"),
    TemplateColumn(
        "group", False, "Tên nhóm; trống là chưa phân nhóm, nhóm chưa có sẽ được tạo.", "Thời tiết cực đoan"
    ),
    TemplateColumn(
        "glossary_terms", True, "Thuật ngữ đã duyệt, cách nhau bằng ;. Metric của rule lấy từ các thuật ngữ này.",
        "Nhiệt độ trung bình"
    ),
    TemplateColumn(
        "conditions",
        True,
        f"Mỗi dòng trong ô là một điều kiện: <cột> {CONDITION_SEPARATOR} <toán tử> {CONDITION_SEPARATOR} <giá trị>. "
        f"Toán tử: {', '.join(sorted(CONDITION_OPERATORS))}. "
        "Giá trị đọc như JSON (35, true, [\"A\", \"B\"]), còn lại là chữ; "
        "is_null và is_not_null không có giá trị.",
        f"gia_tri_so {CONDITION_SEPARATOR} greater_than_or_equal {CONDITION_SEPARATOR} 35",
    ),
    TemplateColumn(
        "exceptions", False, f"Mỗi dòng trong ô là một ngoại lệ: <khi nào> {PAIR_SEPARATOR} <kết quả>; tối đa 50.",
        f"Vùng núi cao {PAIR_SEPARATOR} dùng ngưỡng 32"
    ),
    TemplateColumn(
        "examples",
        True,
        f"Mỗi dòng trong ô là một câu hỏi ví dụ: <câu hỏi> {PAIR_SEPARATOR} <cách hiểu>; từ 1 đến 50 câu.",
        f"Hà Nội có bao nhiêu ngày nắng nóng tháng 6? {PAIR_SEPARATOR} đếm ngày có nhiệt độ từ 35 độ",
    ),
)
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


@dataclass
class RulePlan:
    payload: dict[str, Any]
    rule_id: int | None = None
    revision: ExpertRuleRevision | None = None
    content_changed: bool = True
    new_group: str | None = None


# -------------------------READ---------------------------
def export_rule_template() -> dict[str, str]:
    return write_template(
        RULE_COLUMNS, [[column.example for column in RULE_COLUMNS]], RULE_FILE_NAME, ExpertRuleValidationError
    )


def export_rules() -> dict[str, str]:
    rules, links, terms = expert_rule_repository(), expert_rule_link_repository(), glossary_term_repository()
    rows = []
    for revision in expert_rule_revision_repository().read_all_current():
        rule = rules.read(revision.rule_id)
        if rule is None:
            continue
        dataset = get_dataset(rule.dataset_id)
        column = column_resolver(rule.dataset_id)
        term_ids = [link.target_id for link in links.read_by_revision(revision.id) if link.kind == "glossary"]
        rows.append(
            [
                revision.name,
                dataset.table_name if dataset else f"#{rule.dataset_id}",
                rule.group.name if rule.group else "",
                join_list(_term_name(terms.read(term_id), term_id) for term_id in sorted(term_ids)),
                "\n".join(_condition_line(condition, column) for condition in revision.conditions),
                "\n".join(f"{item['when']} {PAIR_SEPARATOR} {item['outcome']}" for item in revision.exceptions),
                "\n".join(f"{item['question']} {PAIR_SEPARATOR} {item['intent']}" for item in revision.examples),
            ]
        )
    rows.sort(key=lambda row: row[0].casefold())
    return write_table(RULE_COLUMNS, rows, RULE_FILE_NAME, ExpertRuleValidationError)


def preview_rule_import(payload: Any) -> list[ImportRow]:
    datasets = business_datasets_by_name()
    first_rows: dict[str, int] = {}
    result = []
    for number, cells in read_table(payload, RULE_COLUMNS, ExpertRuleValidationError):
        item = ImportRow(row=number, key=cells["name"])
        name_key = normalized_name(cells["name"])
        try:
            if name_key and name_key in first_rows:
                raise ExpertRuleValidationError(f"Rule trùng tên với dòng {first_rows[name_key]}.")
            first_rows.setdefault(name_key, number)
            _plan_rule(item, cells, datasets)
        except SemanticLayerError as error:
            item.action, item.message, item.changes = "error", _rule_message(str(error)), []
        result.append(item)
    return result


# -------------------------CREATE-------------------------
def apply_rule_import(payload: Any, actor_id: int) -> list[ImportRow]:
    rows = preview_rule_import(payload)
    refusal = refusal_message(rows)
    if refusal:
        raise ExpertRuleValidationError(refusal)
    rules, groups = ExpertRuleService(), ExpertRuleGroupService()
    created_groups: dict[str, int] = {}
    for item in rows:
        plan = item.plan
        if item.action == "unchanged":
            continue
        rule_payload = dict(plan.payload)
        if plan.new_group is not None:
            group_key = plan.new_group.casefold()
            if group_key not in created_groups:
                created_groups[group_key] = groups.create({"name": plan.new_group}).id
            rule_payload["group_id"] = created_groups[group_key]
        if plan.rule_id is None:
            rules.create(rule_payload, actor_id)
        elif plan.content_changed:
            rules.update(plan.rule_id, rule_payload, plan.revision.lifecycle_version, actor_id)
        else:
            groups.move_rule(plan.rule_id, rule_payload["group_id"], actor_id)
    return rows


# -------------------------HELPERS------------------------
def _plan_rule(item: ImportRow, cells: dict[str, str], datasets: dict[str, list[Any]]) -> None:
    dataset = dataset_named(cells["dataset"], datasets, ExpertRuleValidationError)
    rule = expert_rule_repository().read_by_normalized_name(normalized_name(cells["name"]))
    revision = expert_rule_revision_repository().read_current(rule.id) if rule else None
    if rule is not None and rule.dataset_id != dataset.id:
        raise ExpertRuleValidationError("Rule đã gắn với một dataset khác; không thể chuyển rule sang dataset khác.")
    column = column_resolver(dataset.id)
    condition_lines = [line for line in cells["conditions"].splitlines() if line.strip()]
    rule_payload = with_term_metrics(
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
            "glossary_term_ids": [_term_id(name) for name in split_list(cells["glossary_terms"])],
        }
    )
    values = normalize_rule_payload(rule_payload, column)
    validate_semantic_links(values)
    plan = RulePlan(rule_payload)
    if "group" in cells:
        group = None
        if cells["group"]:
            group = expert_rule_group_repository().read_by_normalized_name(normalized_name(cells["group"]))
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
    links = expert_rule_link_repository().read_by_revision(revision.id)
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
    elif revision.status == ReviewStatus.APPROVED:
        item.action = "update"
        item.message = "Tạo bản nháp mới chờ duyệt; bản đã duyệt ngừng được dùng cho tới khi bản nháp được duyệt."
        item.message += new_group_note
    else:
        item.action, item.message = "update", "Tạo bản nháp mới chờ duyệt." + new_group_note


def _term_id(name: str) -> int:
    term = glossary_term_repository().read_by_normalized_name(normalized_name(name))
    if term is None:
        raise ExpertRuleValidationError(f"Không có thuật ngữ «{name}».")
    return term.id


def _term_name(term: Any, term_id: int) -> str:
    return term.canonical_name if term else f"#{term_id}"


def _condition(line: str, column: Callable[[Any], Any], dataset: Any) -> dict[str, Any]:
    parts = [part.strip() for part in line.split(CONDITION_SEPARATOR, 2)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ExpertRuleValidationError(f"Điều kiện «{line.strip()}» phải có dạng <cột> | <toán tử> | <giá trị>.")
    column_name, operator = parts[0], parts[1]
    if operator not in CONDITION_OPERATORS:
        raise ExpertRuleValidationError(
            f"Toán tử «{operator}» không hợp lệ; dùng một trong: {', '.join(sorted(CONDITION_OPERATORS))}."
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
