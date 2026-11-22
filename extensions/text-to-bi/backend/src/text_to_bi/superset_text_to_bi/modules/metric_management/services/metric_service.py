from datetime import datetime, timezone
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
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import require_dataset

from ..exceptions import MetricConflictError, MetricNotFoundError, MetricValidationError
from ..models import Metric, metric_domains
from ..repositories import MetricRepository


class MetricService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = MetricRepository(session)
        self.domains = DomainAssignment(session, metric_domains, "metric_id")

    def list_metrics(self, dataset_id: int) -> list[dict[str, Any]]:
        dataset = require_dataset(dataset_id)
        require_dataset_access(dataset)
        manual = [self._manual(row) for row in self.repository.list(dataset_id)]
        native = [self._native(row) for row in self.repository.native(dataset_id)]
        return sorted(manual + native, key=lambda row: (row["name"].casefold(), row["origin"]))

    def get_metric(self, metric_id: UUID) -> dict[str, Any]:
        return self._manual(self._require(metric_id))

    def create_metric(self, values: dict[str, Any]) -> dict[str, Any]:
        dataset = require_dataset(values["dataset_id"])
        require_edit(dataset)
        name, expression = self._validate(values["name"], values["expression"])
        if self.repository.find_name(dataset.id, name):
            raise MetricConflictError("Tên metric đã tồn tại trên dataset này.")
        domain_ids = self._domain_ids(values.get("business_domain_ids") or [])
        row = Metric(dataset_id=dataset.id, name=name, expression=expression)
        self._apply(row, values)
        self.session.add(row)
        self.session.flush()
        self.domains.replace(row.id, domain_ids)
        return self._manual(row)

    def update_metric(self, metric_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        row = self._require(metric_id, lock=True)
        require_edit(require_dataset(row.dataset_id))
        name, expression = self._validate(values.get("name", row.name), values.get("expression", row.expression))
        duplicate = self.repository.find_name(row.dataset_id, name)
        if duplicate is not None and duplicate.id != row.id:
            raise MetricConflictError("Tên metric đã tồn tại trên dataset này.")
        domain_ids = values.get("business_domain_ids")
        if domain_ids is not None:
            domain_ids = self._domain_ids(domain_ids)
        if row.name != name or row.expression != expression or any(
            field in values and getattr(row, field) != values[field]
            for field in ("label", "description", "format", "currency", "metric_type", "warning_text")
        ):
            row.status = "draft"
        row.name, row.expression = name, expression
        self._apply(row, values)
        if domain_ids is not None and self.domains.ids(row.id) != set(domain_ids):
            self.domains.replace(row.id, domain_ids)
            row.updated_at = utc_now()
        self.session.flush()
        return self._manual(row)

    def approve(self, metric_id: UUID) -> dict[str, Any]:
        require_review()
        row = self._require(metric_id, lock=True)
        if row.status != "draft":
            raise MetricConflictError("Chỉ có thể duyệt metric nháp.")
        row.status = "approved"
        self.session.flush()
        return self._manual(row)

    def revoke(self, metric_id: UUID) -> dict[str, Any]:
        require_review()
        row = self._require(metric_id, lock=True)
        if row.status != "approved":
            raise MetricConflictError("Chỉ có thể thu hồi metric đã duyệt.")
        row.status = "revoked"
        self.session.flush()
        return self._manual(row)

    def delete_metric(self, metric_id: UUID) -> None:
        row = self._require(metric_id, lock=True)
        require_edit(require_dataset(row.dataset_id))
        if row.status == "approved":
            require_review()
        self.session.delete(row)
        self.session.flush()

    def resolve(self, kind: str, target_key: str, dataset_id: int) -> dict[str, Any] | None:
        if kind == "metric":
            try:
                row = self.repository.get(UUID(target_key))
            except ValueError:
                return None
            if row is None or row.dataset_id != dataset_id or not row.is_active or row.status != "approved":
                return None
            return self._manual(row)
        if kind == "superset_metric":
            try:
                row = self.repository.native_by_id(int(target_key))
            except ValueError:
                return None
            if row is None or row.table_id != dataset_id:
                return None
            return self._native(row)
        return None

    def _require(self, metric_id: UUID, lock: bool = False) -> Metric:
        row = self.repository.get(metric_id, lock)
        if row is None:
            raise MetricNotFoundError()
        require_dataset_access(require_dataset(row.dataset_id))
        return row

    def _domain_ids(self, domain_ids: list[UUID]) -> list[UUID]:
        if self.domains.unknown(domain_ids):
            raise MetricValidationError("Miền nghiệp vụ không tồn tại.")
        return list(dict.fromkeys(domain_ids))

    @staticmethod
    def _validate(name: str, expression: str) -> tuple[str, str]:
        name, expression = name.strip(), expression.strip()
        if not name or len(name) > 255 or not expression or len(expression) > 10000 or ";" in expression:
            raise MetricValidationError("Tên hoặc biểu thức metric không hợp lệ.")
        return name, expression

    @staticmethod
    def _apply(row: Metric, values: dict[str, Any]) -> None:
        for field in ("label", "description", "format", "currency", "metric_type", "warning_text", "is_active"):
            if field in values:
                setattr(row, field, values[field])

    def _manual(self, row: Metric) -> dict[str, Any]:
        return {
            "id": str(row.id), "origin": "manual", "dataset_id": row.dataset_id, "name": row.name,
            "label": row.label, "expression": row.expression, "description": row.description,
            "format": row.format, "currency": row.currency, "metric_type": row.metric_type,
            "warning_text": row.warning_text, "is_active": row.is_active, "status": row.status,
            "business_domains": self.domains.read_one(row.id), "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _native(row: Any) -> dict[str, Any]:
        created_at = getattr(row, "created_on", None)
        updated_at = getattr(row, "changed_on", None)
        if isinstance(created_at, datetime) and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if isinstance(updated_at, datetime) and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return {
            "id": str(row.id), "origin": "superset", "dataset_id": row.table_id, "name": row.metric_name,
            "label": getattr(row, "verbose_name", None), "expression": row.expression,
            "description": getattr(row, "description", None), "format": getattr(row, "d3format", None),
            "currency": getattr(row, "currency", None), "metric_type": getattr(row, "metric_type", None),
            "warning_text": getattr(row, "warning_text", None), "is_active": True, "status": "approved",
            "business_domains": [],
            "created_at": created_at, "updated_at": updated_at,
        }
