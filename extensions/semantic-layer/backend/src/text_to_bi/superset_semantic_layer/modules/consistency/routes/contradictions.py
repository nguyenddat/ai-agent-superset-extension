from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from superset import db

from ....common.utils.type_formatter import iso_datetime
from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected, require_admin
from ....migrations import ensure_dictionary_tables
from ...superset.services.users import user_names
from ..exceptions import ContradictionCheckConflictError
from ..models import Contradiction
from ..services.judgement import semantic_judge
from ..services.lifecycle import dismissal_reason, found_by
from ..services.review import contradictions_for_review, mark_contradiction_dismissed, refresh_contradictions


class ContradictionRoutes:
    """Routes of SemanticLayerAPI. Contradictions between glossary terms and expert rules, for administrators."""

    @staticmethod
    def _contradiction(row: Contradiction, user_name: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "kind": row.kind,
            "found_by": found_by(row.kind),
            "status": row.status,
            "items": row.items,
            "evidence": row.evidence,
            "explanation": row.explanation,
            "detected_at": iso_datetime(row.detected_at),
            "dismiss_reason": row.dismiss_reason,
            "dismissed_by_name": user_name(row.dismissed_by),
            "dismissed_at": iso_datetime(row.dismissed_at),
        }

    @expose("/contradictions/check", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def check_contradictions(self):
        """Check every current term and rule again and answer the contradictions, open ones first.

        With `{"rules_only": true}` the AI model is not asked; the screen shows the rule-based findings at once and
        then checks again with the model.
        """
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
            contradictions=[self._contradiction(row, user_name) for row in contradictions_for_review()],
            semantic={"status": outcome.status, "unchecked": outcome.unchecked, "message": outcome.message},
        )

    @expose("/contradictions/<int:contradiction_id>/dismiss", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def dismiss_contradiction(self, contradiction_id: int):
        """Accept a contradiction as it is, with a reason; it comes back when either item's content changes."""
        require_admin()
        ensure_dictionary_tables()
        reason = dismissal_reason(request.get_json(silent=True))
        row = mark_contradiction_dismissed(contradiction_id, reason, current_user.id)
        db.session.commit()
        return self.response(200, contradiction=self._contradiction(row, user_names()))
