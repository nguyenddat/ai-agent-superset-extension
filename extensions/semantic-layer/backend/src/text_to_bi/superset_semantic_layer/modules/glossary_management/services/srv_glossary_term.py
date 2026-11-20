from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.core.exceptions import DatasetAccessError
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_dataset
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import get_user

from ..dependencies import glossary_link_repository, glossary_revision_repository, glossary_term_repository
from ..exceptions import (
    GlossaryConflictError,
    GlossarySelfApprovalError,
    GlossaryTermNotFoundError,
    GlossaryValidationError,
)
from ..models import GlossaryTerm, GlossaryTermRevision
from .srv_glossary_event import GlossaryEventService
from .srv_glossary_group import GlossaryGroupService
from .srv_glossary_link import metric_approved, revision_readable, term_readable, validated_links
from .srv_glossary_validation import content_hash, group_id_of, normalize_glossary_payload

TERM_CHANGED = "The glossary term changed; refresh and retry."
NAME_TAKEN = "A glossary term with this canonical name already exists."


class GlossaryTermService:
    def __init__(self) -> None:
        self.terms = glossary_term_repository()
        self.revisions = glossary_revision_repository()
        self.links = glossary_link_repository()
        self.groups = GlossaryGroupService()
        self.events = GlossaryEventService()

    # -------------------------CREATE-------------------------
    def create(self, payload: Any, actor_id: int) -> GlossaryTermRevision:
        values = checked_term_content(payload)
        if self.terms.read_by_normalized_name(values["normalized_name"]) is not None:
            raise GlossaryConflictError(NAME_TAKEN)
        group_id = group_id_of(payload)
        term = GlossaryTerm(
            canonical_name=values["canonical_name"],
            normalized_name=values["normalized_name"],
            steward_id=values["steward_id"],
            group=None if group_id is None else self.groups.require(group_id),
        )
        try:
            self.terms.add(term)
        except IntegrityError as error:
            raise GlossaryConflictError(NAME_TAKEN) from error
        revision = self._create_revision(term.id, 1, values)
        self.events.create(revision, "created", actor_id)
        return revision

    # -------------------------READ---------------------------
    def read(self, term_id: int) -> GlossaryTerm | None:
        return self.terms.read(term_id)

    def require(self, term_id: int) -> GlossaryTerm:
        term = self.terms.read(term_id)
        if term is None:
            raise GlossaryTermNotFoundError()
        if not term_readable(term_id):
            raise DatasetAccessError()
        return term

    def read_revisions(self, term_id: int) -> list[GlossaryTermRevision]:
        return self.revisions.read_by_term(term_id)

    def read_all_current(self) -> list[tuple[GlossaryTerm, GlossaryTermRevision]]:
        result = []
        for term in self.terms.read_all():
            revision = self.revisions.read_current(term.id)
            if revision is not None and revision_readable(revision.id):
                result.append((term, revision))
        return result

    def read_serving(self, term_id: int) -> GlossaryTermRevision | None:
        return self.revisions.read_serving(term_id)

    # -------------------------UPDATE-------------------------
    def update(self, term_id: int, payload: Any, expected_revision: int, actor_id: int) -> GlossaryTermRevision:
        current = self._locked_current(term_id, expected_revision)
        values = checked_term_content(payload)
        if values["normalized_name"] != current.term.normalized_name:
            raise GlossaryValidationError("The canonical name cannot be changed after creation.")
        group_id = group_id_of(payload)
        group = None if group_id is None else self.groups.require(group_id)
        current.term.steward_id = values["steward_id"]
        current.is_current = False
        revision = self._create_revision(term_id, current.revision_number + 1, values)
        self.events.create(revision, "updated", actor_id)
        if "group_id" in payload:
            self.groups.place_term(current.term, group, actor_id)
        return revision

    def approve(
        self, term_id: int, expected_revision: int, actor_id: int, reason: str | None, require_second_reviewer: bool
    ) -> GlossaryTermRevision:
        revision = self._locked_current(term_id, expected_revision)
        if revision.status != ReviewStatus.DRAFT:
            raise GlossaryValidationError("Only the current draft can be approved.")
        if require_second_reviewer and self.events.read_author_id(revision) == actor_id:
            raise GlossarySelfApprovalError()
        revision.status = ReviewStatus.APPROVED.value
        revision.approver_id, revision.approved_at = actor_id, datetime.now(timezone.utc)
        self.events.create(revision, "approved", actor_id, reason)
        return revision

    def revoke(self, term_id: int, expected_revision: int, actor_id: int, reason: str | None) -> GlossaryTermRevision:
        current = self._locked_current(term_id, expected_revision)
        serving = self.revisions.read_serving(term_id)
        if serving is None:
            raise GlossaryValidationError("Only the current approved revision can be revoked.")
        if reason is None:
            raise GlossaryValidationError("A bounded revocation reason is required.")
        serving.status = ReviewStatus.REVOKED.value
        serving.revoker_id, serving.revoked_at = actor_id, datetime.now(timezone.utc)
        self.events.create(serving, "revoked", actor_id, reason)
        return current

    # -------------------------HELPERS------------------------
    def _create_revision(self, term_id: int, revision_number: int, values: dict[str, Any]) -> GlossaryTermRevision:
        links = validated_links(values["links"], get_dataset, metric_approved)
        try:
            revision = self.revisions.create(
                {
                    "term_id": term_id,
                    "revision_number": revision_number,
                    "definition": values["definition"],
                    "synonyms": values["synonyms"],
                    "content_hash": content_hash(values),
                    "status": ReviewStatus.DRAFT.value,
                    "is_current": True,
                }
            )
        except IntegrityError as error:
            raise GlossaryConflictError(TERM_CHANGED) from error
        for link in links:
            self.links.create({"revision_id": revision.id, **link}, flush=False)
        return revision

    def _locked_current(self, term_id: int, expected_revision: int) -> GlossaryTermRevision:
        if self.terms.read_for_update(term_id) is None:
            raise GlossaryTermNotFoundError()
        current = self.revisions.read_current_for_update(term_id)
        if current is None:
            raise GlossaryTermNotFoundError()
        if current.revision_number != expected_revision:
            raise GlossaryConflictError(TERM_CHANGED)
        return current


def checked_term_content(payload: Any) -> dict[str, Any]:
    values = normalize_glossary_payload(payload)
    steward_id = values["steward_id"]
    if steward_id is not None and get_user(steward_id) is None:
        raise GlossaryValidationError("Unknown steward_id.")
    return values
