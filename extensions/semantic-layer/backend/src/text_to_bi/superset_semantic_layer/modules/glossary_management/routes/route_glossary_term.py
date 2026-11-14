from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db

from text_to_bi.superset_semantic_layer.common.public import public_payload
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.exceptions import DatasetAccessError
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import (
    csrf_protected,
    require_admin,
    require_semantic_layer_query,
    require_semantic_layer_view,
    second_reviewer_required,
)
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import active_users, user_names

from ..services.srv_glossary_event import GlossaryEventService
from ..services.srv_glossary_group import GlossaryGroupService
from ..services.srv_glossary_link import discoverable_glossary_terms, link_options, term_readable
from ..services.srv_glossary_term import GlossaryTermService
from ..services.srv_glossary_validation import expected_revision_of, group_id_of, review_reason
from ..utils.util_serializer import (
    serialize_glossary_events,
    serialize_glossary_group,
    serialize_glossary_review_entry,
    serialize_glossary_term,
    serialize_group_reference,
    serialize_users,
)

prefix = "/glossary"


class GlossaryTermRoutes(RouteMixin):
    # -------------------------READ---------------------------
    @expose(prefix, methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_glossary_terms(self):
        """Bản hiện tại của mọi thuật ngữ người gọi được đọc, kèm nhóm và người dùng để chọn phụ trách."""
        require_semantic_layer_view()
        ensure_dictionary_tables()
        user_name = user_names()
        current = GlossaryTermService().read_all_current()
        return self.response(
            200,
            terms=[serialize_glossary_review_entry(term, revision, user_name) for term, revision in current],
            groups=[serialize_glossary_group(group) for group in GlossaryGroupService().read_all()],
            users=serialize_users(active_users()),
            current_user_id=current_user.id,
            require_second_reviewer=second_reviewer_required(),
        )

    @expose(f"{prefix}/options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_glossary_options(self):
        """Dataset, cột vật lý và metric đã duyệt mà thuật ngữ được liên kết tới."""
        require_semantic_layer_view()
        return self.response(200, datasets=link_options())

    @expose(f"{prefix}/<int:term_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_glossary_term(self, term_id: int):
        require_semantic_layer_view()
        ensure_dictionary_tables()
        terms = GlossaryTermService()
        term = terms.require(term_id)
        return self.response(200, term=serialize_glossary_term(term, terms.read_revisions(term_id)))

    @expose(f"{prefix}/<int:term_id>/audit", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_glossary_events(self, term_id: int):
        """Lịch sử tạo, sửa, duyệt, thu hồi và chuyển nhóm của thuật ngữ."""
        require_semantic_layer_view()
        ensure_dictionary_tables()
        if not term_readable(term_id):
            raise DatasetAccessError()
        events = GlossaryEventService().read_history(term_id)
        return self.response(200, events=serialize_glossary_events(events, user_names()))

    @expose(f"{prefix}/discovery", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_glossary_discovery(self):
        """Chỉ thuật ngữ đã duyệt, với liên kết còn mới tới dataset người gọi được đọc."""
        require_semantic_layer_query()
        ensure_dictionary_tables()
        return self.response(200, **public_payload({"terms": discoverable_glossary_terms()}))

    # -------------------------CREATE-------------------------
    @expose(prefix, methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_glossary_term(self):
        require_admin()
        ensure_dictionary_tables()
        revision = GlossaryTermService().create(request.get_json(silent=True), current_user.id)
        db.session.commit()
        return self.response(201, term=serialize_glossary_term(revision.term, [revision]))

    # -------------------------UPDATE-------------------------
    @expose(f"{prefix}/<int:term_id>/draft", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_glossary_term(self, term_id: int):
        """Lưu chỉnh sửa thành bản nháp mới chờ duyệt."""
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        revision = GlossaryTermService().update(term_id, payload, expected_revision_of(payload), current_user.id)
        db.session.commit()
        return self.response(200, term=serialize_glossary_term(revision.term, [revision]))

    @expose(f"{prefix}/<int:term_id>/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_glossary_term(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        revision = GlossaryTermService().approve(
            term_id, expected_revision_of(payload), current_user.id, review_reason(payload), second_reviewer_required()
        )
        db.session.commit()
        return self.response(200, term=serialize_glossary_term(revision.term, [revision]))

    @expose(f"{prefix}/<int:term_id>/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_glossary_term(self, term_id: int):
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        revision = GlossaryTermService().revoke(
            term_id, expected_revision_of(payload), current_user.id, review_reason(payload)
        )
        db.session.commit()
        return self.response(200, term=serialize_glossary_term(revision.term, [revision]))

    @expose(f"{prefix}/<int:term_id>/group", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_glossary_term_group(self, term_id: int):
        """Chuyển thuật ngữ vào nhóm, hoặc bỏ khỏi mọi nhóm với `group_id` null; không cần duyệt."""
        require_admin()
        ensure_dictionary_tables()
        group_id = group_id_of(request.get_json(silent=True))
        term = GlossaryGroupService().move_term(term_id, group_id, current_user.id)
        db.session.commit()
        return self.response(200, term_id=term.id, group=serialize_group_reference(term.group))
