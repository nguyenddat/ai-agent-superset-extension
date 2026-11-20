from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from superset import db

from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import csrf_protected, require_admin
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import user_names

from ..exceptions import ContradictionCheckConflictError
from ..services.srv_contradiction_judgement import semantic_judge
from ..services.srv_contradiction_lifecycle import dismissal_reason
from ..services.srv_contradiction_review import (
    contradictions_for_review,
    mark_contradiction_dismissed,
    refresh_contradictions,
)
from ..utils.util_serializer import serialize_contradiction

prefix = "/contradictions"


class ContradictionRoutes(RouteMixin):
    # -------------------------CREATE-------------------------
    @expose(f"{prefix}/check", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def check_contradictions(self):
        require_admin()
        ensure_dictionary_tables()
        payload = request.get_json(silent=True)
        rules_only = isinstance(payload, dict) and payload.get("rules_only") is True
        # Two checks at once may both add the same new contradiction; the second one is asked to check again.
        try:
            outcome = refresh_contradictions(semantic_judge(), defer_model=rules_only)
            db.session.commit()
        except IntegrityError as error:
            raise ContradictionCheckConflictError() from error
        user_name = user_names()
        return self.response(
            200,
            contradictions=[serialize_contradiction(row, user_name) for row in contradictions_for_review()],
            semantic={"status": outcome.status, "unchecked": outcome.unchecked, "message": outcome.message},
        )

    # -------------------------UPDATE-------------------------
    @expose(f"{prefix}/<int:contradiction_id>/dismiss", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def dismiss_contradiction(self, contradiction_id: int):
        require_admin()
        ensure_dictionary_tables()
        reason = dismissal_reason(request.get_json(silent=True))
        row = mark_contradiction_dismissed(contradiction_id, reason, current_user.id)
        db.session.commit()
        return self.response(200, contradiction=serialize_contradiction(row, user_names()))
