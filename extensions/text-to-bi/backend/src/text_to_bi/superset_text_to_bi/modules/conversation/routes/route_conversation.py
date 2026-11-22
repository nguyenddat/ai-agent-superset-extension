import re
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
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import current_user_id
from text_to_bi.superset_text_to_bi.modules.management_payload import json_payload

from ..dependencies import conversation_service
from ..exceptions import ConversationValidationError
from ..migrations import ensure_conversation_tables
from ..schemas import ConversationCreate, ConversationUpdate, FeedbackIn, ViewIn

RESULT_ID_PATTERN = re.compile(r"^\d+-\d+$")


def conversation_id_from_path(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise ConversationValidationError("ID hội thoại không hợp lệ.") from error


def turn_id_from_path(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise ConversationValidationError("ID lượt hội thoại không hợp lệ.") from error


@api(
    id="text_to_bi_conversation_api", name="Text to BI conversation API",
    description="Stores a user's Text to BI conversations, results, feedback and chart views.",
    resource_name="conversations",
)
class ConversationAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    @expose("/", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_conversation(self):
        body = request_body(ConversationCreate)
        ensure_conversation_tables()
        result = conversation_service().create(body.database_id, current_user_id(), body.title)
        db.session.commit()
        return self.response(201, conversation=json_payload(result))

    @expose("/", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_conversations(self):
        ensure_conversation_tables()
        database_id = request.args.get("database_id", type=int)
        archived_value = request.args.get("archived", default="false").lower()
        if archived_value not in {"true", "false"}:
            raise ConversationValidationError("archived phải là true hoặc false.")
        archived = archived_value == "true"
        query = request.args.get("q")
        limit = request.args.get("limit", default=50, type=int)
        offset = request.args.get("offset", default=0, type=int)
        result = conversation_service().list_conversations(
            current_user_id(), database_id, archived, query, limit, offset,
        )
        return self.response(200, result=json_payload(result))

    @expose("/<conversation_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_conversation(self, conversation_id: str):
        ensure_conversation_tables()
        limit = request.args.get("turns_limit", default=100, type=int)
        offset = request.args.get("turns_offset", default=0, type=int)
        result = conversation_service().detail(
            conversation_id_from_path(conversation_id), current_user_id(), limit, offset,
        )
        return self.response(200, conversation=json_payload(result))

    @expose("/<conversation_id>", methods=("PATCH",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_conversation(self, conversation_id: str):
        body = request_body(ConversationUpdate)
        ensure_conversation_tables()
        result = conversation_service().update(
            conversation_id_from_path(conversation_id), current_user_id(), body.model_dump(exclude_none=True),
        )
        db.session.commit()
        return self.response(200, conversation=json_payload(result))

    @expose("/<conversation_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_conversation(self, conversation_id: str):
        ensure_conversation_tables()
        conversation_service().delete(conversation_id_from_path(conversation_id), current_user_id())
        db.session.commit()
        return self.response(200, message="Đã xóa hội thoại.")

    @expose("/<conversation_id>/turns", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_turns(self, conversation_id: str):
        ensure_conversation_tables()
        limit = request.args.get("limit", default=100, type=int)
        offset = request.args.get("offset", default=0, type=int)
        result = conversation_service().list_turns(
            conversation_id_from_path(conversation_id), current_user_id(), limit, offset,
        )
        return self.response(200, turns=json_payload(result))

    @expose("/<conversation_id>/turns/<turn_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_turn(self, conversation_id: str, turn_id: str):
        ensure_conversation_tables()
        result = conversation_service().get_turn(
            conversation_id_from_path(conversation_id), turn_id_from_path(turn_id), current_user_id(),
        )
        return self.response(200, turn=json_payload(result))

    @expose("/<conversation_id>/turns/<turn_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_turn(self, conversation_id: str, turn_id: str):
        ensure_conversation_tables()
        conversation_service().delete_turn(
            conversation_id_from_path(conversation_id), turn_id_from_path(turn_id), current_user_id(),
        )
        db.session.commit()
        return self.response(200, message="Đã xóa lượt hội thoại.")

    @expose("/<conversation_id>/turns/<turn_id>/feedback", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def put_feedback(self, conversation_id: str, turn_id: str):
        body = request_body(FeedbackIn)
        ensure_conversation_tables()
        result = conversation_service().put_feedback(
            conversation_id_from_path(conversation_id), turn_id_from_path(turn_id),
            current_user_id(), body.model_dump(),
        )
        db.session.commit()
        return self.response(200, feedback=json_payload(result))

    @expose("/<conversation_id>/turns/<turn_id>/feedback", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_feedback(self, conversation_id: str, turn_id: str):
        ensure_conversation_tables()
        conversation_service().delete_feedback(
            conversation_id_from_path(conversation_id), turn_id_from_path(turn_id), current_user_id(),
        )
        db.session.commit()
        return self.response(200, message="Đã xóa đánh giá.")

    @expose("/<conversation_id>/turns/<turn_id>/views/<result_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def put_view(self, conversation_id: str, turn_id: str, result_id: str):
        if not RESULT_ID_PATTERN.fullmatch(result_id):
            raise ConversationValidationError("ID kết quả không hợp lệ.")
        body = request_body(ViewIn)
        ensure_conversation_tables()
        result = conversation_service().put_view(
            conversation_id_from_path(conversation_id), turn_id_from_path(turn_id), result_id,
            current_user_id(), body.chart,
        )
        db.session.commit()
        return self.response(200, view=json_payload(result))

    @expose("/<conversation_id>/turns/<turn_id>/views/<result_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_view(self, conversation_id: str, turn_id: str, result_id: str):
        if not RESULT_ID_PATTERN.fullmatch(result_id):
            raise ConversationValidationError("ID kết quả không hợp lệ.")
        ensure_conversation_tables()
        conversation_service().delete_view(
            conversation_id_from_path(conversation_id), turn_id_from_path(turn_id), result_id, current_user_id(),
        )
        db.session.commit()
        return self.response(200, message="Đã xóa cấu hình biểu đồ.")
