from uuid import UUID

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset.extensions import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_text_to_bi.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION, OPENAPI_TAG
from text_to_bi.superset_text_to_bi.core.security import csrf_protected
from text_to_bi.superset_text_to_bi.core.validation import request_body
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import require_admin, require_view
from text_to_bi.superset_text_to_bi.modules.management_payload import json_payload

from ..dependencies import own_knowledge_service
from ..exceptions import OwnKnowledgeValidationError
from ..migrations import ensure_own_knowledge_tables
from ..schemas import AdminPromote, AdminReview, ClarificationAnswer, ClarificationPush, EntryUpdate


def knowledge_id_from_path(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise OwnKnowledgeValidationError("ID own knowledge không hợp lệ.") from error


@api(
    id="text_to_bi_own_knowledge_api", name="Text to BI own knowledge API",
    description="Captures and manages user-owned knowledge and its administrative review.",
    resource_name="own-knowledge",
)
class OwnKnowledgeAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    @expose("/clarifications", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def push_clarification(self):
        require_view()
        body = request_body(ClarificationPush)
        ensure_own_knowledge_tables()
        result = own_knowledge_service().push_clarification(body.model_dump())
        db.session.commit()
        return self.response(201, clarification=json_payload(result))

    @expose("/clarifications/<clarification_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_clarification(self, clarification_id: str):
        require_view()
        ensure_own_knowledge_tables()
        result = own_knowledge_service().get_clarification(knowledge_id_from_path(clarification_id))
        return self.response(200, clarification=json_payload(result))

    @expose("/clarifications/<clarification_id>/answer", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def answer_clarification(self, clarification_id: str):
        require_view()
        body = request_body(ClarificationAnswer)
        ensure_own_knowledge_tables()
        result = own_knowledge_service().answer_clarification(
            knowledge_id_from_path(clarification_id), body.model_dump(),
        )
        db.session.commit()
        return self.response(200, result=json_payload(result))

    @expose("/agent/entries", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_agent_entries(self):
        require_view()
        dataset_id = request.args.get("dataset_id", type=int)
        if not dataset_id:
            raise OwnKnowledgeValidationError("Cần dataset_id.")
        ensure_own_knowledge_tables()
        entries = own_knowledge_service().agent_entries(dataset_id)
        return self.response(200, entries=json_payload(entries))

    @expose("/agent/entries/<entry_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_own_entry(self, entry_id: str):
        require_view()
        body = request_body(EntryUpdate)
        ensure_own_knowledge_tables()
        entry = own_knowledge_service().update_own_entry(knowledge_id_from_path(entry_id), body.model_dump())
        db.session.commit()
        return self.response(200, entry=json_payload(entry))

    @expose("/agent/entries/<entry_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_own_entry(self, entry_id: str):
        require_view()
        ensure_own_knowledge_tables()
        own_knowledge_service().delete_own_entry(knowledge_id_from_path(entry_id))
        db.session.commit()
        return self.response(200, message="Đã xóa own knowledge.")

    @expose("/admin/entries", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_review_entries(self):
        require_admin()
        ensure_own_knowledge_tables()
        dataset_id = request.args.get("dataset_id", type=int)
        user_id = request.args.get("user_id", type=int)
        status = request.args.get("status")
        entries = own_knowledge_service().review_entries(dataset_id, status, user_id)
        return self.response(200, entries=json_payload(entries))

    @expose("/admin/entries/<entry_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_review_entry(self, entry_id: str):
        require_admin()
        ensure_own_knowledge_tables()
        entry = own_knowledge_service().get_admin_entry(knowledge_id_from_path(entry_id))
        return self.response(200, entry=json_payload(entry))

    @expose("/admin/entries/<entry_id>/review", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def review_entry(self, entry_id: str):
        require_admin()
        body = request_body(AdminReview)
        ensure_own_knowledge_tables()
        entry = own_knowledge_service().review_entry(knowledge_id_from_path(entry_id), body.model_dump())
        db.session.commit()
        return self.response(200, entry=json_payload(entry))

    @expose("/admin/entries/<entry_id>/promote", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def promote_entry(self, entry_id: str):
        require_admin()
        body = request_body(AdminPromote)
        ensure_own_knowledge_tables()
        result = own_knowledge_service().promote_entry(knowledge_id_from_path(entry_id), body.model_dump())
        db.session.commit()
        return self.response(200, result=json_payload(result))
