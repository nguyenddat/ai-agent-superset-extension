from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from superset.extensions import security_manager
from superset.models.dashboard import Dashboard

from text_to_bi.superset_text_to_bi.common.utils.type_formatters import iso_datetime, utc_now
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import current_user_id

from ..exceptions import UserDefinitionNotFoundError, UserDefinitionValidationError
from ..models import UserDefinition
from ..repositories import UserDefinitionRepository

KINDS = {"glossary", "expert_rule"}
REVIEW_STATUSES = {"pending", "promoted", "ignored"}


class OwnKnowledgeService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.definitions = UserDefinitionRepository(session)

    def list_own(self, dashboard_id: int) -> list[dict[str, Any]]:
        self._require_dashboard_access(dashboard_id)
        return [self._serialize(row) for row in self.definitions.list_for_dashboard(current_user_id(), dashboard_id)]

    def get_owned(self, definition_id: UUID) -> UserDefinition:
        row = self.definitions.get_owned(definition_id, current_user_id())
        if row is None:
            raise UserDefinitionNotFoundError()
        return row

    def update_own(self, definition_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        row = self.get_owned(definition_id)
        name, concept, definition = self._parse_content(values, row.kind)
        row.name = name
        row.normalized_name = name.casefold()
        row.concept = concept or row.concept
        row.definition = definition
        row.review_status = "pending"
        row.reviewed_by = None
        row.reviewed_on = None
        row.updated_on = utc_now()
        self.session.flush()
        return self._serialize(row)

    def delete_own(self, definition_id: UUID) -> None:
        self.definitions.delete(self.get_owned(definition_id))

    def save_confirmed(
        self,
        items: list[dict[str, Any]],
        *,
        user_id: int,
        dashboard_id: int,
        question_id: int | None = None,
        session_id: int | None = None,
    ) -> None:
        self._require_dashboard_access(dashboard_id)
        existing = {
            (row.kind, row.normalized_name): row
            for row in self.definitions.list_for_dashboard(user_id, dashboard_id)
        }
        for item in items:
            name, concept, definition = self._parse_content(item, item.get("kind"))
            key = (item["kind"], name.casefold())
            row = existing.get(key)
            if row is None:
                row = UserDefinition(
                    user_id=user_id, dashboard_id=dashboard_id, kind=item["kind"], name=name,
                    normalized_name=name.casefold(), definition=definition,
                )
                self.definitions.create(row)
                existing[key] = row
            row.name = name
            row.normalized_name = name.casefold()
            row.concept = concept
            row.definition = definition
            row.conditions = item.get("conditions")
            row.source_question_id = question_id
            row.source_session_id = session_id
            row.review_status = "pending"
            row.reviewed_by = None
            row.reviewed_on = None
            row.updated_on = utc_now()

    def list_for_review(self) -> list[dict[str, Any]]:
        return [{**self._serialize(row), "user_id": row.user_id} for row in self.definitions.list_for_review()]

    def set_review_status(self, ids: list[UUID], status: str, reviewer_id: int) -> int:
        if status not in REVIEW_STATUSES:
            raise UserDefinitionValidationError("Trạng thái review không hợp lệ.")
        rows = self.definitions.get_many(ids)
        by_id = {row.id: row for row in rows}
        for definition_id in ids:
            row = by_id.get(definition_id)
            if row is None:
                raise UserDefinitionNotFoundError()
            row.review_status = status
            row.reviewed_by = reviewer_id if status != "pending" else None
            row.reviewed_on = utc_now() if status != "pending" else None
        return len(rows)

    def _require_dashboard_access(self, dashboard_id: int) -> None:
        dashboard = self.session.get(Dashboard, dashboard_id)
        if dashboard is None:
            raise UserDefinitionNotFoundError("Không tìm thấy dashboard.")
        security_manager.raise_for_access(dashboard)

    @staticmethod
    def _parse_content(values: Any, kind: Any) -> tuple[str, str | None, str]:
        if kind not in KINDS or not isinstance(values, dict):
            raise UserDefinitionValidationError()
        name, concept, definition = values.get("name"), values.get("concept"), values.get("definition")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
            raise UserDefinitionValidationError("Tên phải là chuỗi không rỗng, tối đa 200 ký tự.")
        if concept is not None and (not isinstance(concept, str) or len(concept.strip()) > 200):
            raise UserDefinitionValidationError("Khái niệm tối đa 200 ký tự.")
        if not isinstance(definition, str) or not definition.strip() or len(definition.strip()) > 2000:
            raise UserDefinitionValidationError("Định nghĩa phải là chuỗi không rỗng, tối đa 2000 ký tự.")
        clean_concept = concept.strip() if isinstance(concept, str) and concept.strip() else None
        return name.strip(), clean_concept, definition.strip()

    @staticmethod
    def _serialize(row: UserDefinition) -> dict[str, Any]:
        return {
            "id": row.id, "kind": row.kind, "name": row.name, "concept": row.concept,
            "definition": row.definition, "conditions": row.conditions, "dashboard_id": row.dashboard_id,
            "source_question_id": row.source_question_id, "review_status": row.review_status,
            "updated_on": iso_datetime(row.updated_on),
        }
