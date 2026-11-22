from typing import Any

from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_role import (
    declare_admin_only_view_menu,
    ensure_role,
    replace_user_roles,
    require_role,
    revoke_permissions,
)
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_user import user_display_name

from ..exceptions import RoleAssignmentError
from .srv_access import ADMIN_ROLE, EDIT_PERMISSION, QUERY_PERMISSION, TEXT_TO_BI_VIEW_MENU, VIEW_PERMISSION

VIEWER_ROLE = "Text to BI Viewer"
EDITOR_ROLE = "Text to BI Editor"
QUERY_ROLE = "Text to BI Query"

VIEW = (VIEW_PERMISSION, TEXT_TO_BI_VIEW_MENU)
EDIT = (EDIT_PERMISSION, TEXT_TO_BI_VIEW_MENU)
QUERY = (QUERY_PERMISSION, TEXT_TO_BI_VIEW_MENU)
# Flask-AppBuilder's @protect checks these before a route runs; the GET routes need `read`, the others `write`.
API_READ = ("can_read", API_CLASS_PERMISSION)
API_WRITE = ("can_write", API_CLASS_PERMISSION)

TEXT_TO_BI_ROLES: dict[str, dict[str, Any]] = {
    VIEWER_ROLE: {
        "description": "Xem các trang quản trị tri thức của những dataset mình đọc được trong Superset.",
        "permissions": [VIEW, API_READ],
    },
    EDITOR_ROLE: {
        "description": "Như Viewer, và sửa từ điển dữ liệu, thuật ngữ, quy tắc, metric của dataset mình đọc được.",
        "permissions": [VIEW, EDIT, API_READ, API_WRITE],
    },
    QUERY_ROLE: {
        "description": "Hỏi dữ liệu trên những dataset mình đọc được trong Superset.",
        "permissions": [QUERY, API_READ, API_WRITE],
    },
}
TEXT_TO_BI_PERMISSIONS = [VIEW, EDIT, QUERY]
# Superset's built-in roles that its role sync fills with every permission not declared admin-only.
BUILT_IN_ROLES = ("Alpha", "Gamma", "Public", "sql_lab")


def declare_text_to_bi_admin_only() -> None:
    declare_admin_only_view_menu(TEXT_TO_BI_VIEW_MENU)


def ensure_text_to_bi_roles() -> None:
    declare_text_to_bi_admin_only()
    for role_name, definition in TEXT_TO_BI_ROLES.items():
        ensure_role(role_name, definition["permissions"])
    ensure_role(ADMIN_ROLE, TEXT_TO_BI_PERMISSIONS)
    for role_name in BUILT_IN_ROLES:
        revoke_permissions(role_name, TEXT_TO_BI_PERMISSIONS)


def text_to_bi_role_options() -> list[dict[str, str]]:
    return [{"name": name, "description": role["description"]} for name, role in TEXT_TO_BI_ROLES.items()]


def checked_role_names(role_names: list[str]) -> list[str]:
    if not all(name in TEXT_TO_BI_ROLES for name in role_names):
        raise RoleAssignmentError()
    return list(dict.fromkeys(role_names))


# Replaces only the user's Text to BI roles; the Superset roles they hold besides stay as they are.
def assign_text_to_bi_roles(user: Any, role_names: list[str]) -> None:
    replace_user_roles(user, TEXT_TO_BI_ROLES, [require_role(name) for name in checked_role_names(role_names)])


def role_assignment(user: Any) -> dict[str, Any]:
    role_names = [role.name for role in user.roles]
    return {
        "user_id": user.id,
        "username": user.username,
        "name": user_display_name(user),
        "is_admin": ADMIN_ROLE in role_names,
        "roles": [name for name in TEXT_TO_BI_ROLES if name in role_names],
        "other_roles": [name for name in role_names if name not in TEXT_TO_BI_ROLES],
    }
