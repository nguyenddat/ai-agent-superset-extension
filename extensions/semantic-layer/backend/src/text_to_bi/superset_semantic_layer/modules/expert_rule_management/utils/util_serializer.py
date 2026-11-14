from collections.abc import Callable
from typing import Any

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import iso_datetime
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_dataset

from ..models import ExpertRule, ExpertRuleAuditEvent, ExpertRuleGroup, ExpertRuleLink, ExpertRuleRevision
from ..services.srv_expert_rule import ExpertRuleService
from ..services.srv_expert_rule_event import ExpertRuleEventService
from ..services.srv_expert_rule_link import column_name, glossary_term_name, physical_column

UserName = Callable[[int | None], str | None]


# -------------------------EXPERT RULE GROUP--------------
def serialize_expert_rule_group(group: ExpertRuleGroup) -> dict[str, Any]:
    return {"id": group.id, "name": group.name, "description": group.description}


def serialize_group_reference(group: ExpertRuleGroup | None) -> dict[str, Any] | None:
    """Tên và ID nhóm của rule; None nếu chưa phân nhóm."""
    return {"id": group.id, "name": group.name} if group else None


# -------------------------EXPERT RULE--------------------
def serialize_expert_rule(revision: ExpertRuleRevision) -> dict[str, Any]:
    return {
        "id": revision.rule_id,
        "revision": revision.revision_number,
        "lifecycle_version": revision.lifecycle_version,
        "schema_version": 2,
        "status": revision.status,
        "name": revision.name,
        "conditions": revision.conditions,
        "exceptions": revision.exceptions,
        "examples": revision.examples,
    }


def serialize_expert_rule_review_entry(
    rule: ExpertRule, revision: ExpertRuleRevision, links: list[ExpertRuleLink], user_name: UserName
) -> dict[str, Any]:
    """Bản hiện tại của rule với trạng thái duyệt, người liên quan và tên cột, thuật ngữ, metric."""
    dataset = get_dataset(rule.dataset_id)
    metric_names = {metric.id: metric.verbose_name or metric.metric_name for metric in getattr(dataset, "metrics", [])}
    column_ids = {condition["field_ref"]["column_dictionary_id"] for condition in revision.conditions}
    author_id = ExpertRuleEventService().read_author_id(revision)
    return {
        **serialize_expert_rule(revision),
        "dataset_id": rule.dataset_id,
        "dataset_name": getattr(dataset, "table_name", None),
        "group": serialize_group_reference(rule.group),
        "state": ExpertRuleService.review_state(revision, links),
        "column_names": {str(column_id): column_name(column_id) for column_id in column_ids},
        "glossary_terms": [
            {"id": link.target_id, "name": glossary_term_name(link.target_id)}
            for link in links
            if link.kind == "glossary"
        ],
        "metrics": [
            {"id": link.target_id, "name": metric_names.get(link.target_id, f"#{link.target_id}")}
            for link in links
            if link.kind == "metric"
        ],
        "author_id": author_id,
        "author_name": user_name(author_id),
        "approver_name": user_name(revision.approver_id),
        "approved_at": iso_datetime(revision.approved_at),
        "revoker_name": user_name(revision.revoker_id),
        "revoked_at": iso_datetime(revision.revoked_at),
    }


def serialize_discovered_rule(rule: ExpertRule, revision: ExpertRuleRevision, links: list[ExpertRuleLink]) -> dict:
    """Rule cho AI Agent: nội dung, nhóm, metric, thuật ngữ và cột vật lý của từng điều kiện."""
    column_ids = {condition["field_ref"]["column_dictionary_id"] for condition in revision.conditions}
    return {
        **serialize_expert_rule(revision),
        # Let a consumer join a rule to catalog metrics and terms and read its conditions by column name.
        "dataset_id": rule.dataset_id,
        # Rules of one group are alike, so a consumer can read them together.
        "group": serialize_group_reference(rule.group),
        "metric_ids": sorted(link.target_id for link in links if link.kind == "metric"),
        "glossary_term_ids": sorted(link.target_id for link in links if link.kind == "glossary"),
        "column_names": {str(column_id): column_name(column_id) for column_id in column_ids},
        # The physical column of each condition, so a consumer can filter a governed metric query by it.
        "condition_columns": {str(column_id): physical_column(column_id) for column_id in column_ids},
    }


# -------------------------EXPERT RULE EVENT--------------
def serialize_expert_rule_events(events: list[ExpertRuleAuditEvent], user_name: UserName) -> list[dict[str, Any]]:
    return [
        {
            "action": event.event_type,
            "revision": event.revision_number,
            "lifecycle_version": event.lifecycle_version,
            "actor_id": event.actor_id,
            "actor_name": user_name(event.actor_id),
            "reason": event.reason,
            "occurred_at": event.occurred_at.isoformat(),
        }
        for event in events
    ]
