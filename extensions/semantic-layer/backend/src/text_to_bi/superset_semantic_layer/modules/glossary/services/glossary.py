from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from superset import security_manager

from ...superset.services.datasets import get_dataset
from ..dependencies import (
    glossary_term_audit_event_repository,
    glossary_term_link_repository,
    glossary_term_repository,
    glossary_term_revision_repository,
)
from ..exceptions import (
    GlossaryConflictError,
    GlossarySelfApprovalError,
    GlossaryTermNotFoundError,
    GlossaryValidationError,
)
from ..models import GlossaryTerm, GlossaryTermAuditEvent, GlossaryTermLink, GlossaryTermRevision
from .discovery import glossary_metric_approved
from .group import place_term, require_group
from .validation import content_hash, group_id_of, normalize_glossary_payload, validated_links

TERM_CHANGED = "The glossary term changed; refresh and retry."
NAME_TAKEN = "A glossary term with this canonical name already exists."


def checked_term_content(payload: Any) -> dict[str, Any]:
    """A term's content as the editor and the file import save it, with its steward checked to exist."""
    values = normalize_glossary_payload(payload)
    steward_id = values["steward_id"]
    if steward_id is not None and security_manager.get_user_by_id(steward_id) is None:
        raise GlossaryValidationError("Unknown steward_id.")
    return values


def _record(revision: GlossaryTermRevision, event_type: str, actor_id: int, reason: str | None = None) -> None:
    glossary_term_audit_event_repository().add(
        GlossaryTermAuditEvent(
            term_id=revision.term_id,
            revision_id=revision.id,
            event_type=event_type,
            actor_id=actor_id,
            reason=reason,
            revision_number=revision.revision_number,
            occurred_at=datetime.now(timezone.utc),
        ),
        flush=False,
    )


def _add_revision(term_id: int, revision_number: int, values: dict[str, Any]) -> GlossaryTermRevision:
    """A new current draft with its links bound to the live datasets, columns and metrics."""
    links = validated_links(values["links"], get_dataset, glossary_metric_approved)
    revision = GlossaryTermRevision(
        term_id=term_id,
        revision_number=revision_number,
        definition=values["definition"],
        synonyms=values["synonyms"],
        content_hash=content_hash(values),
        status="draft",
        is_current=True,
    )
    try:
        glossary_term_revision_repository().add(revision)
    except IntegrityError as error:
        raise GlossaryConflictError(TERM_CHANGED) from error
    link_repository = glossary_term_link_repository()
    for link in links:
        link_repository.add(GlossaryTermLink(revision_id=revision.id, **link), flush=False)
    return revision


def _locked_current(term_id: int, expected_revision: int) -> GlossaryTermRevision:
    """Lock the term, then re-read its current revision; a change since the client read it is a conflict."""
    if glossary_term_repository().lock(term_id) is None:
        raise GlossaryTermNotFoundError()
    current = glossary_term_revision_repository().lock_current(term_id)
    if current is None:
        raise GlossaryTermNotFoundError()
    if current.revision_number != expected_revision:
        raise GlossaryConflictError(TERM_CHANGED)
    return current


def create_draft(payload: Any, actor_id: int) -> GlossaryTermRevision:
    values = checked_term_content(payload)
    term_repository = glossary_term_repository()
    if term_repository.by_normalized_name(values["normalized_name"]) is not None:
        raise GlossaryConflictError(NAME_TAKEN)
    term = GlossaryTerm(
        canonical_name=values["canonical_name"],
        normalized_name=values["normalized_name"],
        steward_id=values["steward_id"],
    )
    group_id = group_id_of(payload)
    if group_id is not None:
        term.group = require_group(group_id)
    try:
        term_repository.add(term)
    except IntegrityError as error:
        raise GlossaryConflictError(NAME_TAKEN) from error
    revision = _add_revision(term.id, 1, values)
    _record(revision, "created", actor_id)
    return revision


def update_draft(term_id: int, payload: Any, expected_revision: int, actor_id: int) -> GlossaryTermRevision:
    """Save an edit as the term's next revision, a draft.

    The approved revision keeps answering the AI Agent until the draft is approved, so a correction never hides the
    term in the meantime. A `group_id` in the payload moves the term at once, outside the draft.
    """
    current = _locked_current(term_id, expected_revision)
    values = checked_term_content(payload)
    if values["normalized_name"] != current.term.normalized_name:
        raise GlossaryValidationError("The canonical name cannot be changed after creation.")
    group_id = group_id_of(payload)
    group = None if group_id is None else require_group(group_id)
    current.term.steward_id = values["steward_id"]
    current.is_current = False
    revision = _add_revision(term_id, current.revision_number + 1, values)
    _record(revision, "updated", actor_id)
    if "group_id" in payload:
        place_term(current.term, group, actor_id)
    return revision


def revision_author_id(revision: GlossaryTermRevision) -> int | None:
    """Who wrote a revision: the actor of its created or updated audit event."""
    event = glossary_term_audit_event_repository().latest_authoring(revision.id)
    return event.actor_id if event else None


def approve_revision(
    term_id: int, expected_revision: int, actor_id: int, reason: str | None, require_second_reviewer: bool
) -> GlossaryTermRevision:
    revision = _locked_current(term_id, expected_revision)
    if revision.status != "draft":
        raise GlossaryValidationError("Only the current draft can be approved.")
    if require_second_reviewer and revision_author_id(revision) == actor_id:
        raise GlossarySelfApprovalError()
    revision.status, revision.approver_id, revision.approved_at = "approved", actor_id, datetime.now(timezone.utc)
    _record(revision, "approved", actor_id, reason)
    return revision


def revoke_revision(term_id: int, expected_revision: int, actor_id: int, reason: str | None) -> GlossaryTermRevision:
    """Stop the revision that answers the AI Agent, even while an edit of it waits for review."""
    current = _locked_current(term_id, expected_revision)
    serving = glossary_term_revision_repository().serving_for(term_id)
    if serving is None:
        raise GlossaryValidationError("Only the current approved revision can be revoked.")
    if reason is None:
        raise GlossaryValidationError("A bounded revocation reason is required.")
    serving.status, serving.revoker_id, serving.revoked_at = "revoked", actor_id, datetime.now(timezone.utc)
    _record(serving, "revoked", actor_id, reason)
    return current
