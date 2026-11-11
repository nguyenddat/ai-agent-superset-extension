from __future__ import annotations

from typing import Any

from ...glossary.services.group_suggestion import (
    EXPERT_RULE_KIND,
    GroupingCandidate,
    grouping_choice,
    suggest_groups,
)
from ..exceptions import ExpertRuleValidationError
from .expert_rule_group import create_rule_group, move_rule, require_rule_group

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


def rule_text(name: str, term_names: list[str], conditions: list[str], examples: list[dict[str, Any]]) -> str:
    """What a rule means, as it is embedded: its name, glossary terms, conditions and example questions with their
    intent. Exceptions are left out: they describe the edge cases, not what the rule is about."""
    questions = "; ".join(f"{example['question']} ({example['intent']})" for example in examples)
    return f"{name}. Thuật ngữ: {', '.join(term_names)}. Điều kiện: {'; '.join(conditions)}. Câu hỏi: {questions}"


def suggest_rule_groups(session: Any) -> dict[str, Any]:
    """Suggested groups of expert rules, each from its current revision."""
    from ...data_dictionary.repositories.column_dictionary import ColumnDictionaryRepository
    from ...glossary.repositories.glossary_term import GlossaryTermRepository
    from ..repositories.expert_rule import ExpertRuleRepository
    from ..repositories.expert_rule_group import ExpertRuleGroupRepository
    from ..repositories.expert_rule_link import ExpertRuleLinkRepository
    from ..repositories.expert_rule_revision import ExpertRuleRevisionRepository

    rules, links = ExpertRuleRepository(session), ExpertRuleLinkRepository(session)
    columns, terms = ColumnDictionaryRepository(session), GlossaryTermRepository(session)
    candidates = []
    for revision in ExpertRuleRevisionRepository(session).current():
        rule = rules.get(revision.rule_id)
        if rule is None:
            continue
        term_names = [
            term.canonical_name
            for link in links.for_revision(revision.id)
            if link.kind == "glossary" and (term := terms.get(link.target_id)) is not None
        ]
        conditions = [_condition_text(condition, columns) for condition in revision.conditions]
        text = rule_text(revision.name, term_names, conditions, revision.examples)
        candidates.append(GroupingCandidate(rule.id, revision.name, text, rule.group_id))
    group_names = {group.id: group.name for group in ExpertRuleGroupRepository(session).by_name()}
    return suggest_groups(EXPERT_RULE_KIND, candidates, group_names)


def apply_rule_grouping(session: Any, payload: Any, actor_id: int) -> tuple[Any, list[int]]:
    """Put the chosen rules in the chosen group, creating it when it is new; returns the group and the rule IDs.

    Each move is a `moved` audit event and keeps the rule's revision, lifecycle version and approval.
    """
    choice = grouping_choice(payload, ExpertRuleValidationError)
    if choice.group_id is not None:
        group = require_rule_group(session, choice.group_id)
    else:
        group = create_rule_group(session, {"name": choice.group_name})
    return group, [move_rule(session, rule_id, group.id, actor_id).id for rule_id in choice.member_ids]


def _condition_text(condition: dict[str, Any], columns: Any) -> str:
    column = columns.get(condition["field_ref"]["column_dictionary_id"])
    column_name = (column.display_name or column.column_name) if column is not None else ""
    value = condition.get("value")
    value_text = ", ".join(map(str, value)) if isinstance(value, list) else "" if value is None else str(value)
    return " ".join(part for part in (column_name, OPERATOR_WORDS.get(condition["operator"], ""), value_text) if part)
