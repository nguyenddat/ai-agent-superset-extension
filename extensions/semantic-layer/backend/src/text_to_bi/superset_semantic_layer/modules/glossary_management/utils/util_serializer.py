from collections.abc import Callable
from typing import Any

from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.common.utils.type_formatter import iso_datetime
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_dataset

from ..models import (
    Contradiction,
    GlossaryTerm,
    GlossaryTermAuditEvent,
    GlossaryTermGroup,
    GlossaryTermLink,
    GlossaryTermRevision,
)
from ..services.srv_contradiction_lifecycle import found_by
from ..services.srv_glossary_event import GlossaryEventService
from ..services.srv_glossary_link import link_is_live, link_target, read_links
from ..services.srv_glossary_term import GlossaryTermService

UserName = Callable[[int | None], str | None]


# -------------------------GLOSSARY GROUP-----------------
def serialize_glossary_group(group: GlossaryTermGroup) -> dict[str, Any]:
    return {"id": group.id, "name": group.name, "description": group.description}


def serialize_group_reference(group: GlossaryTermGroup | None) -> dict[str, Any] | None:
    return {"id": group.id, "name": group.name} if group else None


# -------------------------GLOSSARY TERM------------------
def serialize_glossary_revision(revision: GlossaryTermRevision, links: list[GlossaryTermLink]) -> dict[str, Any]:
    return {
        "id": revision.id,
        "term_id": revision.term_id,
        "revision_number": revision.revision_number,
        "canonical_name": revision.term.canonical_name,
        "definition": revision.definition,
        "synonyms": revision.synonyms or [],
        "status": revision.status,
        "is_current": revision.is_current,
        "created_at": iso_datetime(revision.created_on),
        "approved_at": iso_datetime(revision.approved_at),
        "revoked_at": iso_datetime(revision.revoked_at),
        "links": [
            {
                "kind": link.kind,
                "dataset_id": link.dataset_id,
                "column_name": link.column_name,
                "metric_id": link.metric_id,
            }
            for link in links
        ],
    }


def serialize_glossary_term(term: GlossaryTerm, revisions: list[GlossaryTermRevision]) -> dict[str, Any]:
    serialized = [serialize_glossary_revision(revision, read_links(revision.id)) for revision in revisions]
    return {
        "id": term.id,
        "canonical_name": term.canonical_name,
        "steward_id": term.steward_id,
        "group": serialize_group_reference(term.group),
        "current_revision": next((revision for revision in serialized if revision["is_current"]), None),
        "revisions": serialized,
    }


def serialize_glossary_review_entry(
    term: GlossaryTerm, revision: GlossaryTermRevision, user_name: UserName
) -> dict[str, Any]:
    links = read_links(revision.id)
    entry = serialize_glossary_term(term, [revision])
    stale = not all(link_is_live(link) for link in links)
    author_id = GlossaryEventService().read_author_id(revision)
    serving = GlossaryTermService().read_serving(term.id)
    for serialized, link in zip(entry["current_revision"]["links"], links):
        dataset = get_dataset(link.dataset_id)
        target = link_target(link, dataset) if dataset else None
        serialized["dataset_name"] = dataset.table_name if dataset else None
        if link.kind == "dataset":
            serialized["target_name"] = None
        else:
            fallback = link.column_name if link.kind == "column" else getattr(target, "metric_name", None)
            serialized["target_name"] = getattr(target, "verbose_name", None) or fallback
    return {
        **entry,
        "state": "outdated" if revision.status == ReviewStatus.APPROVED and stale else revision.status,
        # The approved revision still answering the AI Agent while an edit of it waits for review.
        "serving_revision_number": serving.revision_number if serving else None,
        "steward_name": user_name(term.steward_id),
        "author_id": author_id,
        "author_name": user_name(author_id),
        "approver_name": user_name(revision.approver_id),
        "revoker_name": user_name(revision.revoker_id),
    }


# -------------------------GLOSSARY EVENT-----------------
def serialize_glossary_events(events: list[GlossaryTermAuditEvent], user_name: UserName) -> list[dict[str, Any]]:
    return [
        {
            "id": event.id,
            "action": event.event_type,
            "revision_number": event.revision_number,
            "actor_id": event.actor_id,
            "actor_name": user_name(event.actor_id),
            "reason": event.reason,
            "created_at": iso_datetime(event.occurred_at),
        }
        for event in events
    ]


# -------------------------CONTRADICTION------------------
def serialize_contradiction(row: Contradiction, user_name: UserName) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "found_by": found_by(row.kind),
        "status": row.status,
        "items": row.items,
        "evidence": row.evidence,
        "explanation": row.explanation,
        "detected_at": iso_datetime(row.detected_at),
        "dismiss_reason": row.dismiss_reason,
        "dismissed_by_name": user_name(row.dismissed_by),
        "dismissed_at": iso_datetime(row.dismissed_at),
    }


# -------------------------USER---------------------------
def serialize_users(users: list[Any]) -> list[dict[str, Any]]:
    return [{"id": user.id, "name": user.get_full_name().strip() or user.username} for user in users]
