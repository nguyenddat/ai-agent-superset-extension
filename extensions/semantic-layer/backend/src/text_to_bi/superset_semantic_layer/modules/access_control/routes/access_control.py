from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset import db

from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import active_users, require_user

from ....core.database import handle_errors, rollback_on_error
from ....core.security import csrf_protected, require_admin
from ....migrations import ensure_dictionary_tables
from ..services.roles import (
    assign_semantic_layer_roles,
    requested_role_names,
    role_assignment,
    semantic_layer_role_options,
)


class AccessControlRoutes:
    @expose("/role-assignments", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_role_assignments(self):
        require_admin()
        ensure_dictionary_tables()
        return self.response(
            200, roles=semantic_layer_role_options(), users=[role_assignment(user) for user in active_users()]
        )

    @expose("/role-assignments/<int:user_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_role_assignment(self, user_id: int):
        require_admin()
        ensure_dictionary_tables()
        role_names = requested_role_names(request.get_json(silent=True))
        user = require_user(user_id)
        assign_semantic_layer_roles(user, role_names)
        db.session.commit()
        return self.response(200, user=role_assignment(user))
