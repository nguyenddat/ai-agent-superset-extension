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
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import current_user_id, require_admin, require_view
from text_to_bi.superset_text_to_bi.modules.management_payload import json_payload

from ..dependencies import own_knowledge_service
from ..exceptions import UserDefinitionValidationError
from ..migrations import ensure_own_knowledge_tables
from ..schemas import DefinitionUpdate, ReviewUpdate


def definition_id_from_path(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise UserDefinitionValidationError("ID định nghĩa không hợp lệ.") from error


@api(
    id="text_to_bi_own_knowledge_api", name="Text to BI own knowledge API",
    description="Manages signed-in users' own business definitions and admin review.", resource_name="own-knowledge",
)
class OwnKnowledgeAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    @expose("/", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_own(self):
        dashboard_id = request.args.get("dashboard_id", type=int)
        if not dashboard_id:
            raise UserDefinitionValidationError("Cần dashboard_id.")
        require_view()
        ensure_own_knowledge_tables()
        return self.response(200, result=json_payload(own_knowledge_service().list_own(dashboard_id)))

    @expose("/<definition_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_own(self, definition_id: str):
        body = request_body(DefinitionUpdate)
        ensure_own_knowledge_tables()
        result = own_knowledge_service().update_own(definition_id_from_path(definition_id), body.model_dump())
        db.session.commit()
        return self.response(200, result=json_payload(result))

    @expose("/<definition_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_own(self, definition_id: str):
        ensure_own_knowledge_tables()
        own_knowledge_service().delete_own(definition_id_from_path(definition_id))
        db.session.commit()
        return self.response(200, message="Đã xóa định nghĩa cá nhân.")

    @expose("/review", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_review(self):
        require_admin()
        ensure_own_knowledge_tables()
        return self.response(200, definitions=json_payload(own_knowledge_service().list_for_review()))

    @expose("/review", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def set_review(self):
        require_admin()
        body = request_body(ReviewUpdate)
        ensure_own_knowledge_tables()
        updated = own_knowledge_service().set_review_status(body.ids, body.status, current_user_id())
        db.session.commit()
        return self.response(200, updated=updated)
