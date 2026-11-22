from uuid import UUID

from flask_appbuilder.api import expose, permission_name, protect, safe
from superset.extensions import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_text_to_bi.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION, OPENAPI_TAG
from text_to_bi.superset_text_to_bi.core.security import csrf_protected
from text_to_bi.superset_text_to_bi.core.validation import request_body
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import require_view
from text_to_bi.superset_text_to_bi.modules.management_payload import json_payload

from ..dependencies import expert_rule_service
from ..exceptions import ExpertRuleValidationError
from ..migrations import ensure_expert_rule_tables
from ..schemas.schema_expert_rule import ReviewIn, RuleCreate, RuleUpdate


def rule_id_from_path(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise ExpertRuleValidationError("ID quy tắc không hợp lệ.") from error


@api(
    id="text_to_bi_expert_rule_api", name="Text to BI expert rule API",
    description="Manages expert rules and their revisions for Superset datasets.", resource_name="expert-rules",
)
class TextToBIExpertRuleAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    @expose("/datasets/<int:dataset_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_rules(self, dataset_id: int):
        require_view()
        ensure_expert_rule_tables()
        return self.response(200, rules=json_payload(expert_rule_service().list_rules(dataset_id)))

    @expose("/datasets/<int:dataset_id>/discovery", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def discovery(self, dataset_id: int):
        require_view()
        ensure_expert_rule_tables()
        return self.response(200, rules=json_payload(expert_rule_service().discovery(dataset_id)))

    @expose("/datasets/<int:dataset_id>/options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def options(self, dataset_id: int):
        require_view()
        ensure_expert_rule_tables()
        return self.response(200, options=json_payload(expert_rule_service().options(dataset_id)))

    @expose("/<rule_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_rule(self, rule_id: str):
        require_view()
        ensure_expert_rule_tables()
        return self.response(200, rule=json_payload(expert_rule_service().get_rule(rule_id_from_path(rule_id))))

    @expose("/<rule_id>/revisions", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_revisions(self, rule_id: str):
        require_view()
        ensure_expert_rule_tables()
        revisions = expert_rule_service().list_revisions(rule_id_from_path(rule_id))
        return self.response(200, revisions=json_payload(revisions))

    @expose("/", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_rule(self):
        body = request_body(RuleCreate)
        ensure_expert_rule_tables()
        rule = expert_rule_service().create_rule(body.model_dump())
        db.session.commit()
        return self.response(201, rule=json_payload(rule))

    @expose("/<rule_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_rule(self, rule_id: str):
        body = request_body(RuleUpdate)
        ensure_expert_rule_tables()
        rule = expert_rule_service().update_rule(rule_id_from_path(rule_id), body.model_dump())
        db.session.commit()
        return self.response(200, rule=json_payload(rule))

    @expose("/<rule_id>/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve(self, rule_id: str):
        body = request_body(ReviewIn)
        ensure_expert_rule_tables()
        rule = expert_rule_service().approve(rule_id_from_path(rule_id), body.expected_revision)
        db.session.commit()
        return self.response(200, rule=json_payload(rule))

    @expose("/<rule_id>/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke(self, rule_id: str):
        body = request_body(ReviewIn)
        ensure_expert_rule_tables()
        rule = expert_rule_service().revoke(rule_id_from_path(rule_id), body.expected_revision)
        db.session.commit()
        return self.response(200, rule=json_payload(rule))

    @expose("/<rule_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_rule(self, rule_id: str):
        ensure_expert_rule_tables()
        expert_rule_service().delete_rule(rule_id_from_path(rule_id))
        db.session.commit()
        return self.response(200, message="Đã xóa quy tắc.")
