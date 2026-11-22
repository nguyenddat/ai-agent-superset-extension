from flask_appbuilder.api import expose, permission_name, protect, safe
from superset.extensions import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_text_to_bi.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION, OPENAPI_TAG
from text_to_bi.superset_text_to_bi.core.security import csrf_protected
from text_to_bi.superset_text_to_bi.core.validation import request_body
from text_to_bi.superset_text_to_bi.migrations import ensure_tables
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_user import (
    active_users,
    require_user,
    user_display_name,
)

from ..schemas.schema_auth import CurrentUserOut, RoleAssignmentIn, RoleAssignmentOut, RoleAssignmentsOut
from ..services.srv_access import can_edit_datasets, can_query_datasets, can_view, current_user, is_admin, require_admin
from ..services.srv_roles import assign_text_to_bi_roles, role_assignment, text_to_bi_role_options


@api(
    id="text_to_bi_auth_api",
    name="Text to BI auth API",
    description="Tells the signed-in user what Text to BI lets them do, and lets an admin assign the Text to BI roles.",
    resource_name="auth",
)
class AuthAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    # -------------------------READ---------------------------
    @expose("/me", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_me(self):
        user = current_user()
        access = {
            "is_admin": is_admin(), "can_view": can_view(), "can_edit": can_edit_datasets(),
            "can_query": can_query_datasets(),
        }
        # The page opens with this call, so the first user with any access bootstraps the tables and roles.
        if any(access.values()):
            ensure_tables()
        current = CurrentUserOut(user_id=user.id, username=user.username, name=user_display_name(user), **access)
        return self.response(200, **current.model_dump(mode="json"))

    @expose("/role-assignments", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_role_assignments(self):
        require_admin()
        ensure_tables()
        assignments = RoleAssignmentsOut(
            roles=text_to_bi_role_options(), users=[role_assignment(user) for user in active_users()]
        )
        return self.response(200, **assignments.model_dump(mode="json"))

    # -------------------------UPDATE-------------------------
    @expose("/role-assignments/<int:user_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_role_assignment(self, user_id: int):
        require_admin()
        body = request_body(RoleAssignmentIn)
        ensure_tables()
        user = require_user(user_id)
        assign_text_to_bi_roles(user, body.roles)
        db.session.commit()
        return self.response(200, **RoleAssignmentOut.model_validate(role_assignment(user)).model_dump(mode="json"))
