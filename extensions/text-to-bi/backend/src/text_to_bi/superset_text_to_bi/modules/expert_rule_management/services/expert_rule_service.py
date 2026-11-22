import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from text_to_bi.superset_text_to_bi.common.utils.type_formatters import utc_now
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import (
    require_dataset_access,
    require_edit,
    require_review,
)
from text_to_bi.superset_text_to_bi.modules.glossary_management.models import GlossaryTerm
from text_to_bi.superset_text_to_bi.modules.glossary_management.services import GlossaryService
from text_to_bi.superset_text_to_bi.modules.management_domains import DomainAssignment
from text_to_bi.superset_text_to_bi.modules.metric_management.services import MetricService
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import dataset_columns, require_dataset

from ..exceptions import ExpertRuleConflictError, ExpertRuleNotFoundError, ExpertRuleValidationError
from ..models import ExpertRule, ExpertRuleGlossaryLink, ExpertRuleMetricLink, ExpertRuleRevision, expert_rule_domains
from ..repositories import ExpertRuleRepository


class ExpertRuleService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ExpertRuleRepository(session)
        self.glossary = GlossaryService(session)
        self.metrics = MetricService(session)
        self.domains = DomainAssignment(session, expert_rule_domains, "rule_id")

    def list_rules(self, dataset_id: int) -> list[dict[str, Any]]:
        require_dataset_access(require_dataset(dataset_id))
        return [self._serialize(row) for row in self.repository.list(dataset_id)]

    def get_rule(self, rule_id: UUID) -> dict[str, Any]:
        return self._serialize(self._rule(rule_id))

    def list_revisions(self, rule_id: UUID) -> list[dict[str, Any]]:
        row = self._rule(rule_id)
        return [self._revision(revision) for revision in self.repository.revisions(row.id)]

    def create_rule(self, values: dict[str, Any]) -> dict[str, Any]:
        dataset = require_dataset(values["dataset_id"])
        require_edit(dataset)
        name = " ".join(values["name"].split())
        if not name or self.repository.find_name(dataset.id, name.casefold()):
            raise ExpertRuleConflictError("Tên quy tắc đã tồn tại trên dataset này.")
        content = self._content(values, dataset.id)
        domain_ids = self._domain_ids(values.get("business_domain_ids") or [])
        row = ExpertRule(dataset_id=dataset.id, name=name, normalized_name=name.casefold())
        self.session.add(row)
        self.session.flush()
        self.domains.replace(row.id, domain_ids)
        self._add_revision(row.id, 1, content)
        return self._serialize(row)

    def update_rule(self, rule_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        row = self._rule(rule_id, lock=True)
        require_edit(require_dataset(row.dataset_id))
        current = self.repository.revisions(row.id)[0]
        self._expected(current, values["expected_revision"])
        content = self._content(values, row.dataset_id)
        domain_ids = self._domain_ids(values.get("business_domain_ids") or [])
        same = (
            current.description == content["description"] and current.conditions == content["conditions"]
            and current.exceptions == content["exceptions"] and current.examples == content["examples"]
            and self._glossary_targets(current.id) == content["glossary"]
            and self._metric_targets(current.id) == content["metrics"]
        )
        if self.domains.ids(row.id) != set(domain_ids):
            self.domains.replace(row.id, domain_ids)
            row.updated_at = utc_now()
        if not same or current.status == "revoked":
            row.updated_at = utc_now()
            self._add_revision(row.id, current.number + 1, content)
        self.session.flush()
        return self._serialize(row)

    def approve(self, rule_id: UUID, expected_revision: int) -> dict[str, Any]:
        require_review()
        row = self._rule(rule_id, lock=True)
        current = self.repository.revisions(row.id)[0]
        self._expected(current, expected_revision)
        if current.status != "draft":
            raise ExpertRuleConflictError("Chỉ có thể duyệt bản nháp hiện tại.")
        if not self._revision_is_live(row, current):
            raise ExpertRuleConflictError("Liên kết hoặc điều kiện đã thay đổi; hãy sửa bản nháp trước khi duyệt.")
        current.status = "approved"
        row.updated_at = utc_now()
        self.session.flush()
        return self._serialize(row)

    def revoke(self, rule_id: UUID, expected_revision: int) -> dict[str, Any]:
        require_review()
        row = self._rule(rule_id, lock=True)
        revisions = self.repository.revisions(row.id)
        self._expected(revisions[0], expected_revision)
        serving = self._serving(revisions)
        if serving is None:
            raise ExpertRuleConflictError("Quy tắc chưa có bản được duyệt để thu hồi.")
        content = {
            "description": serving.description, "conditions": serving.conditions,
            "exceptions": serving.exceptions, "examples": serving.examples,
            "glossary": self._glossary_targets(serving.id), "metrics": self._metric_targets(serving.id),
        }
        row.updated_at = utc_now()
        self._add_revision(row.id, revisions[0].number + 1, content, status="revoked")
        return self._serialize(row)

    def delete_rule(self, rule_id: UUID) -> None:
        row = self._rule(rule_id, lock=True)
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
            if serving is None or not self._revision_is_live(row, serving):
                continue
            result.append({
                "id": row.id, "dataset_id": row.dataset_id, "name": row.name,
                "business_domains": self.domains.read_one(row.id), "description": serving.description,
                "conditions": serving.conditions, "exceptions": serving.exceptions, "examples": serving.examples,
                "glossary_term_ids": [link.term_id for link in self.repository.glossary_links(serving.id)],
                "metric_refs": self._metric_refs(serving.id),
            })
        return result

    def options(self, dataset_id: int) -> dict[str, Any]:
        dataset = require_dataset(dataset_id)
        require_dataset_access(dataset)
        terms = []
        for term in self.glossary.repository.list(dataset_id):
            serving = self.glossary.serving_revision(term.id)
            if serving is not None and self._term_matches_dataset(dataset_id, serving.id):
                terms.append({"id": term.id, "name": term.canonical_name})
        return {
            "dataset_id": dataset_id,
            "columns": [{"name": col.column_name, "data_type": str(getattr(col, "type", "") or "")}
                        for col in dataset_columns(dataset)],
            "glossary_terms": terms,
            "metrics": [metric for metric in self.metrics.list_metrics(dataset_id) if metric["is_active"]],
        }

    def _content(self, values: dict[str, Any], dataset_id: int) -> dict[str, Any]:
        columns = {col.column_name for col in dataset_columns(require_dataset(dataset_id))}
        conditions = [item if isinstance(item, dict) else item.model_dump() for item in values["conditions"]]
        for condition in conditions:
            if condition["column_name"] not in columns:
                raise ExpertRuleValidationError("Cột điều kiện không thuộc dataset của quy tắc.")
        glossary_ids = values["glossary_term_ids"]
        metric_refs = [item if isinstance(item, dict) else item.model_dump() for item in values["metric_refs"]]
        if (len(set(glossary_ids)) != len(glossary_ids)
                or len({(m["kind"], m["target_key"]) for m in metric_refs}) != len(metric_refs)):
            raise ExpertRuleValidationError("Liên kết thuật ngữ hoặc metric bị trùng.")
        glossary = []
        for term_id in sorted(glossary_ids):
            term = self.session.get(GlossaryTerm, term_id)
            if term is None or term.dataset_id != dataset_id:
                raise ExpertRuleValidationError("Thuật ngữ không thuộc dataset đang chọn.")
            serving = self.glossary.serving_revision(term_id)
            if serving is None or not self._term_matches_dataset(dataset_id, serving.id):
                raise ExpertRuleValidationError("Thuật ngữ cần bản đã duyệt liên kết tới dataset của quy tắc.")
            glossary.append((term_id, serving.id))
        metrics = []
        for ref in sorted(metric_refs, key=lambda item: (item["kind"], item["target_key"])):
            metric = self.metrics.resolve(ref["kind"], ref["target_key"], dataset_id)
            if metric is None:
                raise ExpertRuleValidationError("Metric không thuộc dataset hoặc không còn hoạt động.")
            metrics.append((ref["kind"], ref["target_key"], self._metric_fingerprint(metric)))
        return {
            "description": values["description"].strip() or None if values["description"] else None,
            "conditions": conditions,
            "exceptions": [item if isinstance(item, dict) else item.model_dump() for item in values["exceptions"]],
            "examples": [item if isinstance(item, dict) else item.model_dump() for item in values["examples"]],
            "glossary": glossary, "metrics": metrics,
        }

    def _add_revision(self, rule_id: UUID, number: int, content: dict[str, Any], status: str = "draft") -> None:
        revision = ExpertRuleRevision(rule_id=rule_id, number=number, description=content["description"],
                                      conditions=content["conditions"], exceptions=content["exceptions"],
                                      examples=content["examples"], status=status)
        self.session.add(revision)
        self.session.flush()
        self.session.add_all([
            ExpertRuleGlossaryLink(revision_id=revision.id, term_id=term_id, glossary_revision_id=revision_id)
            for term_id, revision_id in content["glossary"]
        ])
        self.session.add_all([
            ExpertRuleMetricLink(revision_id=revision.id, kind=kind, target_key=target_key, fingerprint=fingerprint)
            for kind, target_key, fingerprint in content["metrics"]
        ])
        self.session.flush()

    def _revision_is_live(self, rule: ExpertRule, revision: ExpertRuleRevision) -> bool:
        dataset = require_dataset(rule.dataset_id)
        columns = {col.column_name for col in dataset_columns(dataset)}
        if any(condition["column_name"] not in columns for condition in revision.conditions):
            return False
        glossary_links = self.repository.glossary_links(revision.id)
        if not glossary_links:
            return False
        for link in glossary_links:
            term = self.session.get(GlossaryTerm, link.term_id)
            if term is None or term.dataset_id != rule.dataset_id:
                return False
            serving = self.glossary.serving_revision(link.term_id)
            if serving is None or serving.id != link.glossary_revision_id:
                return False
            if not self._term_matches_dataset(rule.dataset_id, serving.id):
                return False
        for link in self.repository.metric_links(revision.id):
            metric = self.metrics.resolve(link.kind, link.target_key, rule.dataset_id)
            if metric is None or self._metric_fingerprint(metric) != link.fingerprint:
                return False
        return True

    def _term_matches_dataset(self, dataset_id: int, revision_id: UUID) -> bool:
        return bool(self.glossary.live_links(dataset_id, revision_id))

    @staticmethod
    def _metric_fingerprint(metric: dict[str, Any]) -> str:
        value = [metric["dataset_id"], metric["name"], metric["expression"], metric["description"], metric["is_active"]]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _glossary_targets(self, revision_id: UUID) -> list[tuple[UUID, UUID]]:
        return [(link.term_id, link.glossary_revision_id) for link in self.repository.glossary_links(revision_id)]

    def _metric_targets(self, revision_id: UUID) -> list[tuple[str, str, str]]:
        return [(link.kind, link.target_key, link.fingerprint) for link in self.repository.metric_links(revision_id)]

    def _metric_refs(self, revision_id: UUID) -> list[dict[str, str]]:
        return [
            {"kind": link.kind, "target_key": link.target_key}
            for link in self.repository.metric_links(revision_id)
        ]

    def _rule(self, rule_id: UUID, lock: bool = False) -> ExpertRule:
        row = self.repository.get(rule_id, lock)
        if row is None:
            raise ExpertRuleNotFoundError()
        require_dataset_access(require_dataset(row.dataset_id))
        return row

    def _domain_ids(self, domain_ids: list[UUID]) -> list[UUID]:
        if self.domains.unknown(domain_ids):
            raise ExpertRuleValidationError("Miền nghiệp vụ không tồn tại.")
        return list(dict.fromkeys(domain_ids))

    @staticmethod
    def _expected(current: ExpertRuleRevision, expected: int) -> None:
        if current.number != expected:
            raise ExpertRuleConflictError()

    @staticmethod
    def _serving(revisions: list[ExpertRuleRevision]) -> ExpertRuleRevision | None:
        for revision in revisions:
            if revision.status == "revoked":
                return None
            if revision.status == "approved":
                return revision
        return None

    def _revision(self, row: ExpertRuleRevision) -> dict[str, Any]:
        return {
            "number": row.number, "status": row.status, "description": row.description,
            "conditions": row.conditions, "exceptions": row.exceptions, "examples": row.examples,
            "glossary_term_ids": [link.term_id for link in self.repository.glossary_links(row.id)],
            "metric_refs": self._metric_refs(row.id), "created_at": row.created_at,
        }

    def _serialize(self, row: ExpertRule) -> dict[str, Any]:
        revisions = self.repository.revisions(row.id)
        serving = self._serving(revisions)
        return {
            "id": row.id, "dataset_id": row.dataset_id, "name": row.name,
            "business_domains": self.domains.read_one(row.id), "current": self._revision(revisions[0]),
            "serving": self._revision(serving) if serving else None,
            "is_discoverable": serving is not None and self._revision_is_live(row, serving),
            "created_at": row.created_at, "updated_at": row.updated_at,
        }
