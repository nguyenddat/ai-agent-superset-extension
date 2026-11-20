from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from superset import db

from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import csrf_protected, require_admin
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables

from ..services.srv_glossary_group import GlossaryGroupService
from ..utils.util_serializer import serialize_glossary_group

prefix = "/glossary/groups"
suggestion_prefix = "/glossary/group-suggestions"


class GlossaryGroupRoutes(RouteMixin):
    # -------------------------CREATE-------------------------
    @expose(prefix, methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_glossary_group(self):
        require_admin()
        ensure_dictionary_tables()
        group = GlossaryGroupService().create(request.get_json(silent=True))
        db.session.commit()
        return self.response(201, group=serialize_glossary_group(group))

    # -------------------------UPDATE-------------------------
    @expose(f"{prefix}/<int:group_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_glossary_group(self, group_id: int):
        require_admin()
        ensure_dictionary_tables()
        group = GlossaryGroupService().update(group_id, request.get_json(silent=True))
        db.session.commit()
        return self.response(200, group=serialize_glossary_group(group))

    # -------------------------DELETE-------------------------
    @expose(f"{prefix}/<int:group_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_glossary_group(self, group_id: int):
        require_admin()
        ensure_dictionary_tables()
        moved_term_ids = GlossaryGroupService().delete(group_id, current_user.id)
        db.session.commit()
        return self.response(200, moved_term_ids=moved_term_ids)

    # -------------------------SUGGESTION---------------------
    @expose(suggestion_prefix, methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_glossary_group_suggestions(self):
        require_admin()
        ensure_dictionary_tables()
        suggestions = GlossaryGroupService().suggest()
        try:
            db.session.commit()
        except IntegrityError:
            # Another request cached the same text first; the vectors in hand are the same.
            db.session.rollback()
        return self.response(200, **suggestions)

    @expose(f"{suggestion_prefix}/apply", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def apply_glossary_group_suggestion(self):
        require_admin()
        ensure_dictionary_tables()
        group, moved_term_ids = GlossaryGroupService().apply_suggestion(request.get_json(silent=True), current_user.id)
        db.session.commit()
        return self.response(200, group=serialize_glossary_group(group), moved_term_ids=moved_term_ids)

    @expose(f"{suggestion_prefix}/dismiss", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def dismiss_glossary_group_suggestion(self):
        require_admin()
        ensure_dictionary_tables()
        fingerprint = GlossaryGroupService.dismiss_suggestion(request.get_json(silent=True), current_user.id)
        db.session.commit()
        return self.response(200, fingerprint=fingerprint)
