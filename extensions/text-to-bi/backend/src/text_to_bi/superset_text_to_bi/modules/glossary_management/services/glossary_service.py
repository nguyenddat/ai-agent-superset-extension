from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from text_to_bi.superset_text_to_bi.common.utils.type_formatters import utc_now
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import (
    require_dataset_access,
    require_edit,
    require_review,
)
from text_to_bi.superset_text_to_bi.modules.management_domains import DomainAssignment
from text_to_bi.superset_text_to_bi.modules.metric_management.services import MetricService
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import dataset_columns, require_dataset

from ..exceptions import GlossaryConflictError, GlossaryNotFoundError, GlossaryValidationError
from ..models import GlossaryLink, GlossaryRevision, GlossaryTerm, glossary_term_domains
from ..repositories import GlossaryRepository


class GlossaryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = GlossaryRepository(session)
        self.metrics = MetricService(session)
        self.domains = DomainAssignment(session, glossary_term_domains, "term_id")

    def list_terms(self, dataset_id: int) -> list[dict[str, Any]]:
        require_dataset_access(require_dataset(dataset_id))
        return [self._serialize(row) for row in self.repository.list(dataset_id)]

    def get_term(self, term_id: UUID) -> dict[str, Any]:
        return self._serialize(self._term(term_id))

    def list_revisions(self, term_id: UUID) -> list[dict[str, Any]]:
        row = self._term(term_id)
        return [self._revision(revision) for revision in self.repository.revisions(row.id)]

    def serving_revision(self, term_id: UUID) -> GlossaryRevision | None:
        row = self._term(term_id)
        return self._serving(self.repository.revisions(row.id))

    def live_links(self, dataset_id: int, revision_id: UUID) -> list[dict[str, str]]:
        return [link for link in self._links(revision_id) if self._link_live(dataset_id, link)]

    def create_term(self, values: dict[str, Any]) -> dict[str, Any]:
        dataset = require_dataset(values["dataset_id"])
        require_edit(dataset)
        name = " ".join(values["canonical_name"].split())
        if not name or self.repository.find_name(dataset.id, name.casefold()):
            raise GlossaryConflictError("Tên thuật ngữ đã tồn tại trên dataset này.")
        content = self._content(values, dataset.id, name)
        domain_ids = self._domain_ids(values.get("business_domain_ids") or [])
        row = GlossaryTerm(dataset_id=dataset.id, canonical_name=name, normalized_name=name.casefold())
        self.session.add(row)
        self.session.flush()
        self.domains.replace(row.id, domain_ids)
        self._add_revision(row.id, 1, content)
        return self._serialize(row)

    def update_term(self, term_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        row = self._term(term_id, lock=True)
        require_edit(require_dataset(row.dataset_id))
        current = self.repository.revisions(row.id)[0]
        self._expected(current, values["expected_revision"])
        content = self._content(values, row.dataset_id, row.canonical_name)
        domain_ids = self._domain_ids(values.get("business_domain_ids") or [])
        same = (current.definition == content["definition"] and current.synonyms == content["synonyms"]
                and self._links(current.id) == content["links"])
        if self.domains.ids(row.id) != set(domain_ids):
            self.domains.replace(row.id, domain_ids)
            row.updated_at = utc_now()
        if not same or current.status == "revoked":
            row.updated_at = utc_now()
            self._add_revision(row.id, current.number + 1, content)
        self.session.flush()
        return self._serialize(row)

    def approve(self, term_id: UUID, expected_revision: int) -> dict[str, Any]:
        require_review()
        row = self._term(term_id, lock=True)
        current = self.repository.revisions(row.id)[0]
        self._expected(current, expected_revision)
        if current.status != "draft":
            raise GlossaryConflictError("Chỉ có thể duyệt bản nháp hiện tại.")
        current.status = "approved"
        row.updated_at = utc_now()
        self.session.flush()
        return self._serialize(row)

    def revoke(self, term_id: UUID, expected_revision: int) -> dict[str, Any]:
        require_review()
        row = self._term(term_id, lock=True)
        revisions = self.repository.revisions(row.id)
        self._expected(revisions[0], expected_revision)
        serving = self._serving(revisions)
        if serving is None:
            raise GlossaryConflictError("Thuật ngữ chưa có bản được duyệt để thu hồi.")
        row.updated_at = utc_now()
        self._add_revision(row.id, revisions[0].number + 1, {
            "definition": serving.definition, "synonyms": list(serving.synonyms), "links": self._links(serving.id),
        }, status="revoked")
        return self._serialize(row)

    def delete_term(self, term_id: UUID) -> None:
        row = self._term(term_id, lock=True)
        require_edit(require_dataset(row.dataset_id))
        if self._serving(self.repository.revisions(row.id)) is not None:
            require_review()
        self.session.delete(row)
        self.session.flush()

    def discovery(self, dataset_id: int) -> list[dict[str, Any]]:
        require_dataset_access(require_dataset(dataset_id))
        result = []
        for row in self.repository.list(dataset_id):
            serving = self._serving(self.repository.revisions(row.id))
            if serving is not None:
                result.append({
                    "id": row.id, "name": row.canonical_name, "definition": serving.definition,
                    "synonyms": serving.synonyms, "business_domains": self.domains.read_one(row.id),
                    "links": self.live_links(dataset_id, serving.id),
                })
        return result

    def _content(self, values: dict[str, Any], dataset_id: int, name: str) -> dict[str, Any]:
        definition = values["definition"].strip()
        if not definition:
            raise GlossaryValidationError("Cần nhập định nghĩa thuật ngữ.")
        synonyms, seen = [], {name.casefold()}
        for raw in values["synonyms"]:
            synonym = " ".join(raw.split())
            if not synonym or len(synonym) > 255 or synonym.casefold() in seen:
                raise GlossaryValidationError("Từ đồng nghĩa trống hoặc trùng lặp.")
            seen.add(synonym.casefold())
            synonyms.append(synonym)
        links = []
        for item in values["links"]:
            link = item if isinstance(item, dict) else item.model_dump()
            normalized = {"kind": link["kind"], "target_key": link["target_key"].strip()}
            if not self._link_live(dataset_id, normalized):
                raise GlossaryValidationError("Liên kết không thuộc dataset hoặc không còn tồn tại.")
            if normalized in links:
                raise GlossaryValidationError("Liên kết thuật ngữ bị trùng.")
            links.append(normalized)
        links.sort(key=lambda link: (link["kind"], link["target_key"]))
        return {"definition": definition, "synonyms": synonyms, "links": links}

    def _link_live(self, dataset_id: int, link: dict[str, str]) -> bool:
        if link["kind"] == "table":
            return link["target_key"] == str(dataset_id)
        if link["kind"] == "column":
            return any(
                column.column_name == link["target_key"]
                for column in dataset_columns(require_dataset(dataset_id))
            )
        return self.metrics.resolve(link["kind"], link["target_key"], dataset_id) is not None

    def _add_revision(self, term_id: UUID, number: int, content: dict[str, Any], status: str = "draft") -> None:
        revision = GlossaryRevision(term_id=term_id, number=number, definition=content["definition"],
                                    synonyms=content["synonyms"], status=status)
        self.session.add(revision)
        self.session.flush()
        self.session.add_all([GlossaryLink(revision_id=revision.id, **link) for link in content["links"]])
        self.session.flush()

    def _links(self, revision_id: UUID) -> list[dict[str, str]]:
        return [{"kind": row.kind, "target_key": row.target_key} for row in self.repository.links(revision_id)]

    def _term(self, term_id: UUID, lock: bool = False) -> GlossaryTerm:
        row = self.repository.get(term_id, lock)
        if row is None:
            raise GlossaryNotFoundError()
        require_dataset_access(require_dataset(row.dataset_id))
        return row

    def _domain_ids(self, domain_ids: list[UUID]) -> list[UUID]:
        if self.domains.unknown(domain_ids):
            raise GlossaryValidationError("Miền nghiệp vụ không tồn tại.")
        return list(dict.fromkeys(domain_ids))

    @staticmethod
    def _expected(current: GlossaryRevision, expected: int) -> None:
        if current.number != expected:
            raise GlossaryConflictError()

    @staticmethod
    def _serving(revisions: list[GlossaryRevision]) -> GlossaryRevision | None:
        for revision in revisions:
            if revision.status == "revoked":
                return None
            if revision.status == "approved":
                return revision
        return None

    def _revision(self, row: GlossaryRevision) -> dict[str, Any]:
        return {"number": row.number, "status": row.status, "definition": row.definition,
                "synonyms": row.synonyms, "links": self._links(row.id), "created_at": row.created_at}

    def _serialize(self, row: GlossaryTerm) -> dict[str, Any]:
        revisions = self.repository.revisions(row.id)
        serving = self._serving(revisions)
        return {
            "id": row.id, "dataset_id": row.dataset_id, "canonical_name": row.canonical_name,
            "business_domains": self.domains.read_one(row.id), "current": self._revision(revisions[0]),
            "serving": self._revision(serving) if serving else None,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }
