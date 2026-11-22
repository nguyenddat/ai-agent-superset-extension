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

from ..dependencies import glossary_service
from ..exceptions import GlossaryValidationError
from ..migrations import ensure_glossary_tables
from ..schemas.schema_glossary import GlossaryCreate, GlossaryUpdate, ReviewIn


def term_id_from_path(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise GlossaryValidationError("ID thuật ngữ không hợp lệ.") from error


@api(
    id="text_to_bi_glossary_api", name="Text to BI glossary API",
    description="Manages glossary terms and their revisions for Superset datasets.", resource_name="glossary",
)
class TextToBIGlossaryAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    @expose("/datasets/<int:dataset_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_terms(self, dataset_id: int):
        require_view()
        ensure_glossary_tables()
        return self.response(200, terms=json_payload(glossary_service().list_terms(dataset_id)))

    @expose("/datasets/<int:dataset_id>/discovery", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def discovery(self, dataset_id: int):
        require_view()
        ensure_glossary_tables()
        return self.response(200, terms=json_payload(glossary_service().discovery(dataset_id)))

    @expose("/<term_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_term(self, term_id: str):
        require_view()
        ensure_glossary_tables()
        return self.response(200, term=json_payload(glossary_service().get_term(term_id_from_path(term_id))))

    @expose("/<term_id>/revisions", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_revisions(self, term_id: str):
        require_view()
        ensure_glossary_tables()
        revisions = glossary_service().list_revisions(term_id_from_path(term_id))
        return self.response(200, revisions=json_payload(revisions))

    @expose("/", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_term(self):
        body = request_body(GlossaryCreate)
        ensure_glossary_tables()
        term = glossary_service().create_term(body.model_dump())
        db.session.commit()
        return self.response(201, term=json_payload(term))

    @expose("/<term_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_term(self, term_id: str):
        body = request_body(GlossaryUpdate)
        ensure_glossary_tables()
        term = glossary_service().update_term(term_id_from_path(term_id), body.model_dump())
        db.session.commit()
        return self.response(200, term=json_payload(term))

    @expose("/<term_id>/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve(self, term_id: str):
        body = request_body(ReviewIn)
        ensure_glossary_tables()
        term = glossary_service().approve(term_id_from_path(term_id), body.expected_revision)
        db.session.commit()
        return self.response(200, term=json_payload(term))

    @expose("/<term_id>/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke(self, term_id: str):
        body = request_body(ReviewIn)
        ensure_glossary_tables()
        term = glossary_service().revoke(term_id_from_path(term_id), body.expected_revision)
        db.session.commit()
        return self.response(200, term=json_payload(term))

    @expose("/<term_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_term(self, term_id: str):
        ensure_glossary_tables()
        glossary_service().delete_term(term_id_from_path(term_id))
        db.session.commit()
        return self.response(200, message="Đã xóa thuật ngữ.")
