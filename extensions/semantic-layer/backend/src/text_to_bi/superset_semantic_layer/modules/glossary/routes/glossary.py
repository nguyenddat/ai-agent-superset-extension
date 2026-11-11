from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db

from ....common.utils.table_file import import_report
from ....common.utils.type_formatter import iso_datetime
from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected, require_admin, second_reviewer_required
from ....migrations import ensure_dictionary_tables
from ...superset.services.datasets import datasets_by_name, get_dataset, is_internal_dataset
from ...superset.services.users import user_names
from ..dependencies import (
    glossary_term_audit_event_repository,
    glossary_term_group_repository,
    glossary_term_repository,
    glossary_term_revision_repository,
)
from ..exceptions import GlossaryTermNotFoundError
from ..models import GlossaryTerm, GlossaryTermGroup, GlossaryTermLink, GlossaryTermRevision
from ..services.discovery import (
    discoverable_glossary_terms,
    glossary_link_target,
    glossary_links,
    glossary_metric_approved,
)
from ..services.glossary import approve_revision, create_draft, revision_author_id, revoke_revision, update_draft
from ..services.group import create_group, delete_group, group_reference, move_term, update_group
from ..services.term_file import apply_term_import, export_terms, preview_term_import
from ..services.validation import expected_revision_of, glossary_link_fingerprint, group_id_of, review_reason


class GlossaryRoutes:
    """Routes of SemanticLayerAPI. The Business Glossary: governed terms, their lifecycle and discovery."""

    @staticmethod
    def _glossary_revision(revision: GlossaryTermRevision, links: list[GlossaryTermLink]) -> dict[str, Any]:
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

    def _glossary_term(self, term: GlossaryTerm, revisions: list[GlossaryTermRevision]) -> dict[str, Any]:
        serialized = [self._glossary_revision(revision, glossary_links(revision.id)) for revision in revisions]
        current = next((revision for revision in serialized if revision["is_current"]), None)
        return {
            "id": term.id,
            "canonical_name": term.canonical_name,
            "steward_id": term.steward_id,
            "group": group_reference(term.group),
            "current_revision": current,
            "revisions": serialized,
        }

    @staticmethod
    def _glossary_group(group: GlossaryTermGroup) -> dict[str, Any]:
        return {"id": group.id, "name": group.name, "description": group.description}

    def _glossary_term_by_id(self, term_id: int) -> GlossaryTerm | None:
        return glossary_term_repository().get(term_id)

    def _glossary_link_is_live(self, link: GlossaryTermLink) -> bool:
        """The linked object is unchanged since the term was saved, and a linked metric is still approved."""
        if self._glossary_live_fingerprint(link) != link.fingerprint:
            return False
        if link.kind != "metric":
            return True
        dataset = get_dataset(link.dataset_id)
        return glossary_metric_approved(dataset, glossary_link_target(link, dataset))

    def _glossary_live_fingerprint(self, link: GlossaryTermLink) -> str | None:
        dataset = get_dataset(link.dataset_id)
        if dataset is None:
            return None
        target = glossary_link_target(link, dataset)
        if link.kind != "dataset" and target is None:
            return None
        return glossary_link_fingerprint(dataset, link.kind, target)

    def _glossary_review_entry(self, term: GlossaryTerm, revision: GlossaryTermRevision, user_name: Any) -> dict:
        """A term's current revision with its review state, the people behind it and readable link labels."""
        links = glossary_links(revision.id)
        entry = self._glossary_term(term, [revision])
        stale = not all(self._glossary_link_is_live(link) for link in links)
        author_id = revision_author_id(revision)
        serving = glossary_term_revision_repository().serving_for(term.id)
        current = entry["current_revision"]
        for serialized, link in zip(current["links"], links):
            dataset = get_dataset(link.dataset_id)
            target = glossary_link_target(link, dataset) if dataset else None
            serialized["dataset_name"] = dataset.table_name if dataset else None
            if link.kind == "dataset":
                serialized["target_name"] = None
            else:
                fallback = link.column_name if link.kind == "column" else getattr(target, "metric_name", None)
                serialized["target_name"] = getattr(target, "verbose_name", None) or fallback
        return {
            **entry,
            "state": "outdated" if revision.status == "approved" and stale else revision.status,
            # The approved revision still answering the AI Agent while an edit of it waits for review.
            "serving_revision_number": serving.revision_number if serving else None,
            "steward_name": user_name(term.steward_id),
            "author_id": author_id,
            "author_name": user_name(author_id),
            "approver_name": user_name(revision.approver_id),
            "revoker_name": user_name(revision.revoker_id),
        }

    @expose("/glossary", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_glossary(self):
        require_admin()
        ensure_dictionary_tables()
        user_name = user_names()
        terms = []
        revision_repository = glossary_term_revision_repository()
        for term in glossary_term_repository().by_canonical_name():
            revision = revision_repository.current_for(term.id)
            if revision is not None:
                terms.append(self._glossary_review_entry(term, revision, user_name))
        return self.response(
            200,
            terms=terms,
            groups=[self._glossary_group(group) for group in glossary_term_group_repository().by_name()],
            users=self._active_users(),
            current_user_id=current_user.id,
            require_second_reviewer=second_reviewer_required(),
        )

    @expose("/glossary/options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def glossary_options(self):
        """What a term may link to: each dataset with its physical active columns and its saved metrics."""
        require_admin()
        datasets = []
        for dataset in datasets_by_name():
            if is_internal_dataset(dataset):
                continue
            datasets.append(
                {
                    "id": dataset.id,
                    "name": dataset.table_name,
                    "columns": [
                        {"column_name": column.column_name, "name": column.verbose_name or column.column_name}
                        for column in dataset.columns
                        if column.is_active is True and not column.expression
                    ],
                    # A term builds on approved metrics only, so a metric must pass review before a term can name it.
                    "metrics": [
                        {"id": metric.id, "name": metric.verbose_name or metric.metric_name}
                        for metric in dataset.metrics
                        if glossary_metric_approved(dataset, metric)
                    ],
                }
            )
        datasets.sort(key=lambda item: item["name"].casefold())
        return self.response(200, datasets=datasets)

    @expose("/glossary/<int:term_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_glossary(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        term = self._glossary_term_by_id(term_id)
        if term is None:
            raise GlossaryTermNotFoundError()
        revisions = glossary_term_revision_repository().for_term(term_id)
        return self.response(200, term=self._glossary_term(term, revisions))

    @expose("/glossary", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_glossary(self):
        require_admin()
        ensure_dictionary_tables()
        revision = create_draft(request.get_json(silent=True), current_user.id)
        db.session.commit()
        return self.response(201, term=self._glossary_term(revision.term, [revision]))

    @expose("/glossary/<int:term_id>/draft", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_glossary_draft(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        revision = update_draft(term_id, payload, expected_revision_of(payload), current_user.id)
        db.session.commit()
        return self.response(200, term=self._glossary_term(revision.term, [revision]))

    @expose("/glossary/<int:term_id>/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_glossary(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        revision = approve_revision(
            term_id, expected_revision_of(payload), current_user.id, review_reason(payload), second_reviewer_required()
        )
        db.session.commit()
        return self.response(200, term=self._glossary_term(revision.term, [revision]))

    @expose("/glossary/<int:term_id>/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_glossary(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        revision = revoke_revision(term_id, expected_revision_of(payload), current_user.id, review_reason(payload))
        db.session.commit()
        return self.response(200, term=self._glossary_term(revision.term, [revision]))

    @expose("/glossary/<int:term_id>/group", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def move_glossary_term(self, term_id: int):
        """Move a term into a group, or out of every group with a null `group_id`; no review is needed."""
        require_admin()
        ensure_dictionary_tables()
        term = move_term(term_id, group_id_of(request.get_json(silent=True)), current_user.id)
        db.session.commit()
        return self.response(200, term_id=term.id, group=group_reference(term.group))

    @expose("/glossary/groups", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_glossary_group(self):
        require_admin()
        ensure_dictionary_tables()
        group = create_group(request.get_json(silent=True))
        db.session.commit()
        return self.response(201, group=self._glossary_group(group))

    @expose("/glossary/groups/<int:group_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_glossary_group(self, group_id: int):
        require_admin()
        ensure_dictionary_tables()
        group = update_group(group_id, request.get_json(silent=True))
        db.session.commit()
        return self.response(200, group=self._glossary_group(group))

    @expose("/glossary/groups/<int:group_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_glossary_group(self, group_id: int):
        """Delete a group; its terms become ungrouped and keep their approval."""
        require_admin()
        ensure_dictionary_tables()
        moved_term_ids = delete_group(group_id, current_user.id)
        db.session.commit()
        return self.response(200, moved_term_ids=moved_term_ids)

    @expose("/glossary/file", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def export_glossary_file(self):
        """Every term as a CSV file, or XLSX with `?format=xlsx`: the template the import reads back."""
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, **export_terms(request.args.get("format", "csv")))

    @expose("/glossary/file/preview", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @handle_errors
    def preview_glossary_file(self):
        """What importing the uploaded file would do to each row; nothing is saved."""
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, **import_report(preview_term_import(request.get_json(silent=True))))

    @expose("/glossary/file/import", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def import_glossary_file(self):
        """Create and update the terms of the uploaded file as drafts in one transaction; a failing row saves none."""
        require_admin()
        ensure_dictionary_tables()
        rows = apply_term_import(request.get_json(silent=True), current_user.id)
        db.session.commit()
        return self.response(200, **import_report(rows))

    @expose("/glossary/<int:term_id>/audit", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def glossary_audit(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        events = glossary_term_audit_event_repository().for_term(term_id)
        user_name = user_names()
        return self.response(
            200,
            events=[
                {
                    "id": row.id,
                    "action": row.event_type,
                    "revision_number": row.revision_number,
                    "actor_id": row.actor_id,
                    "actor_name": user_name(row.actor_id),
                    "reason": row.reason,
                    "created_at": iso_datetime(row.occurred_at),
                }
                for row in events
            ],
        )

    @expose("/glossary/discovery", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def glossary_discovery(self):
        """Return only approved, current, fresh links to caller-authorized datasets."""
        ensure_dictionary_tables()
        return self.response(200, terms=discoverable_glossary_terms())

