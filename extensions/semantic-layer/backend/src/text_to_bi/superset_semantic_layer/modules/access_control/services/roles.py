from typing import Any

from text_to_bi.superset_semantic_layer.modules.superset.services.srv_role import (
    declare_admin_only_view_menu,
    ensure_role,
    replace_user_roles,
    require_role,
    revoke_permissions,
)

from ....core.security import QUERY_PERMISSION, SEMANTIC_LAYER_VIEW_MENU, VIEW_PERMISSION
from ..exceptions import RoleAssignmentError

SEMANTIC_LAYER_API = "text_to_bi_semantic_layer_api"
EXPERT_RULE_API = "text_to_bi_expert_rule_api"
# Every AI Agent API shares this class permission; asking the agent is querying the Semantic Layer as the user.
AI_AGENT_API = "text_to_bi_chat_api"

VIEWER_ROLE = "Semantic Layer Viewer"
QUERY_ROLE = "Semantic Layer Query"

# Each role's own permission plus the API permissions Flask-AppBuilder's @protect checks before the route runs.
SEMANTIC_LAYER_ROLES: dict[str, dict[str, Any]] = {
    VIEWER_ROLE: {
        "description": "Xem Metrics, Business Glossary và Expert Rules ở chế độ chỉ đọc.",
        "permissions": [
            (VIEW_PERMISSION, SEMANTIC_LAYER_VIEW_MENU),
            ("can_read", SEMANTIC_LAYER_API),
            ("can_read", EXPERT_RULE_API),
        ],
    },
    QUERY_ROLE: {
        "description": (
            "Hỏi AI Agent: đọc semantic catalog và chạy metric đã duyệt. Nút “Chạy thử” ở Metrics cần thêm nhóm Viewer."
        ),
        "permissions": [
            (QUERY_PERMISSION, SEMANTIC_LAYER_VIEW_MENU),
            ("can_read", SEMANTIC_LAYER_API),
            ("can_read", EXPERT_RULE_API),
            ("can_read", AI_AGENT_API),
            ("can_write", AI_AGENT_API),
        ],
    },
}
SEMANTIC_LAYER_PERMISSIONS = [(VIEW_PERMISSION, SEMANTIC_LAYER_VIEW_MENU), (QUERY_PERMISSION, SEMANTIC_LAYER_VIEW_MENU)]
# Superset's built-in roles that its role sync fills with every permission not declared admin-only.
BUILT_IN_ROLES = ("Alpha", "Gamma", "Public", "sql_lab")


def declare_semantic_layer_admin_only() -> None:
    declare_admin_only_view_menu(SEMANTIC_LAYER_VIEW_MENU)


def ensure_semantic_layer_roles() -> None:
    declare_semantic_layer_admin_only()
    for role_name, definition in SEMANTIC_LAYER_ROLES.items():
        ensure_role(role_name, definition["permissions"])
    ensure_role("Admin", SEMANTIC_LAYER_PERMISSIONS)
    for role_name in BUILT_IN_ROLES:
        revoke_permissions(role_name, SEMANTIC_LAYER_PERMISSIONS)


def semantic_layer_role_options() -> list[dict[str, str]]:
    return [{"name": name, "description": role["description"]} for name, role in SEMANTIC_LAYER_ROLES.items()]


def requested_role_names(body: Any) -> list[str]:
    role_names = body.get("roles") if isinstance(body, dict) else None
    if not isinstance(role_names, list) or not all(name in SEMANTIC_LAYER_ROLES for name in role_names):
        raise RoleAssignmentError()
    return list(dict.fromkeys(role_names))


def assign_semantic_layer_roles(user: Any, role_names: list[str]) -> None:
    replace_user_roles(user, SEMANTIC_LAYER_ROLES, [require_role(name) for name in role_names])


def role_assignment(user: Any) -> dict[str, Any]:
    role_names = [role.name for role in user.roles]
    return {
        "id": user.id,
        "username": user.username,
        "name": user.get_full_name().strip() or user.username,
        "is_admin": "Admin" in role_names,
        "roles": [name for name in SEMANTIC_LAYER_ROLES if name in role_names],
        "other_roles": [name for name in role_names if name not in SEMANTIC_LAYER_ROLES],
    }
