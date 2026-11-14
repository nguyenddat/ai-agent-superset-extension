from typing import Any

from sqlalchemy.exc import IntegrityError

from text_to_bi.superset_semantic_layer.modules.data_dictionary.dependencies import column_dictionary_repository
from text_to_bi.superset_semantic_layer.modules.glossary_management.dependencies import glossary_term_repository
from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_group_suggestion import (
    EXPERT_RULE_KIND,
    GroupingCandidate,
    dismiss_suggestion,
    grouping_choice,
    suggest_groups,
)

from ..dependencies import (
    expert_rule_group_repository,
    expert_rule_link_repository,
    expert_rule_repository,
    expert_rule_revision_repository,
)
from ..exceptions import (
    ExpertRuleConflictError,
    ExpertRuleGroupNotFoundError,
    ExpertRuleNotFoundError,
    ExpertRuleValidationError,
)
from ..models import ExpertRule, ExpertRuleGroup
from .srv_expert_rule_event import ExpertRuleEventService
from .srv_expert_rule_validation import normalize_group_payload

GROUP_NAME_TAKEN = "Đã có nhóm rule cùng tên."
UNGROUPED = "Chưa phân nhóm"
# How a condition's operator reads in the text a rule is embedded from.
OPERATOR_WORDS = {
    "equals": "bằng",
    "not_equals": "khác",
    "contains": "chứa",
    "not_contains": "không chứa",
    "greater_than": "lớn hơn",
    "greater_than_or_equal": "từ",
    "less_than": "nhỏ hơn",
    "less_than_or_equal": "tối đa",
    "in": "thuộc",
    "not_in": "không thuộc",
    "is_null": "để trống",
    "is_not_null": "có giá trị",
}


class ExpertRuleGroupService:
    def __init__(self) -> None:
        self.groups = expert_rule_group_repository()
        self.rules = expert_rule_repository()
        self.revisions = expert_rule_revision_repository()
        self.events = ExpertRuleEventService()

    # -------------------------CREATE-------------------------
    def create(self, payload: Any) -> ExpertRuleGroup:
        values = normalize_group_payload(payload)
        if self.groups.read_by_normalized_name(values["normalized_name"]) is not None:
            raise ExpertRuleConflictError(GROUP_NAME_TAKEN)
        try:
            return self.groups.create(values)
        except IntegrityError as error:
            raise ExpertRuleConflictError(GROUP_NAME_TAKEN) from error

    # -------------------------READ---------------------------
    def read_all(self) -> list[ExpertRuleGroup]:
        return self.groups.read_all()

    def require(self, group_id: int) -> ExpertRuleGroup:
        group = self.groups.read(group_id)
        if group is None:
            raise ExpertRuleGroupNotFoundError()
        return group

    # -------------------------UPDATE-------------------------
    def update(self, group_id: int, payload: Any) -> ExpertRuleGroup:
        """Đổi tên hoặc mô tả nhóm; rule trong nhóm giữ nguyên và không cần duyệt lại."""
        group = self.require(group_id)
        if not isinstance(payload, dict):
            raise ExpertRuleValidationError("Nhóm rule chỉ có tên và mô tả.")
        values = normalize_group_payload({"name": group.name, "description": group.description, **payload})
        same_name = self.groups.read_by_normalized_name(values["normalized_name"])
        if same_name is not None and same_name.id != group.id:
            raise ExpertRuleConflictError(GROUP_NAME_TAKEN)
        try:
            return self.groups.update(group, values)
        except IntegrityError as error:
            raise ExpertRuleConflictError(GROUP_NAME_TAKEN) from error

    def move_rule(self, rule_id: int, group_id: int | None, actor_id: int) -> ExpertRule:
        """Chuyển rule vào nhóm, hoặc bỏ khỏi mọi nhóm khi `group_id` là None."""
        rule = self.rules.read_for_update(rule_id)
        if rule is None:
            raise ExpertRuleNotFoundError()
        self.place_rule(rule, None if group_id is None else self.require(group_id), actor_id)
        return rule

    def place_rule(self, rule: ExpertRule, group: ExpertRuleGroup | None, actor_id: int) -> None:
        """Đặt rule vào nhóm và ghi sự kiện `moved`; phiên bản vòng đời giữ nguyên nên lượt duyệt đang chờ còn hợp lệ."""
        previous = rule.group
        if (previous.id if previous else None) == (group.id if group else None):
            return
        rule.group = group
        rule.group_id = group.id if group else None
        revision = self.revisions.read_current(rule.id)
        if revision is None:
            return
        reason = f"{previous.name if previous else UNGROUPED} → {group.name if group else UNGROUPED}"
        self.events.create(revision, "moved", actor_id, reason)

    # -------------------------DELETE-------------------------
    def delete(self, group_id: int, actor_id: int) -> list[int]:
        """Xóa nhóm, các rule trong nhóm thành chưa phân nhóm; trả về ID các rule đã chuyển."""
        group = self.require(group_id)
        rules = self.rules.read_in_group(group.id)
        for rule in rules:
            self.place_rule(rule, None, actor_id)
        self.groups.delete(group)
        return [rule.id for rule in rules]

    # -------------------------SUGGESTION---------------------
    def suggest(self) -> dict[str, Any]:
        """Gợi ý nhóm cho rule chưa phân nhóm có nghĩa gần nhau, đọc từ bản hiện tại."""
        links, terms = expert_rule_link_repository(), glossary_term_repository()
        columns = column_dictionary_repository()
        candidates = []
        for revision in self.revisions.read_all_current():
            rule = self.rules.read(revision.rule_id)
            if rule is None:
                continue
            term_names = [
                term.canonical_name
                for link in links.read_by_revision(revision.id)
                if link.kind == "glossary" and (term := terms.read(link.target_id)) is not None
            ]
            conditions = [_condition_text(condition, columns) for condition in revision.conditions]
            text = rule_text(revision.name, term_names, conditions, revision.examples)
            candidates.append(GroupingCandidate(rule.id, revision.name, text, rule.group_id))
        group_names = {group.id: group.name for group in self.groups.read_all()}
        return suggest_groups(EXPERT_RULE_KIND, candidates, group_names)

    def apply_suggestion(self, payload: Any, actor_id: int) -> tuple[ExpertRuleGroup, list[int]]:
        """Chuyển các rule quản trị viên giữ lại vào nhóm có sẵn hoặc nhóm mới; trả về nhóm và ID rule."""
        choice = grouping_choice(payload, ExpertRuleValidationError)
        if choice.group_id is not None:
            group = self.require(choice.group_id)
        else:
            group = self.create({"name": choice.group_name})
        return group, [self.move_rule(rule_id, group.id, actor_id).id for rule_id in choice.member_ids]

    @staticmethod
    def dismiss_suggestion(payload: Any, actor_id: int) -> str:
        """Bỏ qua một gợi ý để không gợi ý lại; trả về fingerprint."""
        return dismiss_suggestion(EXPERT_RULE_KIND, payload, actor_id, ExpertRuleValidationError)


def rule_text(name: str, term_names: list[str], conditions: list[str], examples: list[dict[str, Any]]) -> str:
    """Nghĩa của rule để embedding: tên, thuật ngữ, điều kiện và câu hỏi ví dụ; bỏ ngoại lệ vì chỉ là ca biên."""
    questions = "; ".join(f"{example['question']} ({example['intent']})" for example in examples)
    return f"{name}. Thuật ngữ: {', '.join(term_names)}. Điều kiện: {'; '.join(conditions)}. Câu hỏi: {questions}"


def _condition_text(condition: dict[str, Any], columns: Any) -> str:
    column = columns.read(condition["field_ref"]["column_dictionary_id"])
    column_name = (column.display_name or column.column_name) if column is not None else ""
    value = condition.get("value")
    value_text = ", ".join(map(str, value)) if isinstance(value, list) else "" if value is None else str(value)
    return " ".join(part for part in (column_name, OPERATOR_WORDS.get(condition["operator"], ""), value_text) if part)
