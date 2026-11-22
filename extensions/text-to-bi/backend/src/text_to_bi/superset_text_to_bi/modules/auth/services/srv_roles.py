from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_role import (
    declare_admin_only_view_menu,
    ensure_role,
    replace_user_roles,
    require_role,
    revoke_permissions,
)

from ..exceptions import RoleAssignmentError
from ..models import Role
from ..repositories import RoleRepository
from .srv_access import (
    ADMIN_ROLE,
    EDIT_PERMISSION,
    QUERY_PERMISSION,
    REVIEW_PERMISSION,
    TEXT_TO_BI_VIEW_MENU,
    VIEW_PERMISSION,
)
from .srv_user import UserService

VIEWER_ROLE = "Text to BI Viewer"
EDITOR_ROLE = "Text to BI Editor"
STEWARD_ROLE = "Text to BI Steward"
QUERY_ROLE = "Text to BI Query"

VIEW = (VIEW_PERMISSION, TEXT_TO_BI_VIEW_MENU)
EDIT = (EDIT_PERMISSION, TEXT_TO_BI_VIEW_MENU)
REVIEW = (REVIEW_PERMISSION, TEXT_TO_BI_VIEW_MENU)
QUERY = (QUERY_PERMISSION, TEXT_TO_BI_VIEW_MENU)
# Flask-AppBuilder's @protect checks these before a route runs; GET needs `read`, writes need `write`.
API_READ = ("can_read", API_CLASS_PERMISSION)
API_WRITE = ("can_write", API_CLASS_PERMISSION)

TEXT_TO_BI_ROLES: dict[str, dict[str, Any]] = {
    VIEWER_ROLE: {
        "description": "Xem metadata của những dataset user được quyền đọc trong Superset.",
        "permissions": [VIEW, API_READ],
    },
    EDITOR_ROLE: {
        "description": "Tạo, sửa và xóa bản nháp metadata trên những dataset user được quyền đọc.",
        "permissions": [VIEW, EDIT, API_READ, API_WRITE],
    },
    STEWARD_ROLE: {
        "description": "Quản lý metadata semantic, gồm duyệt, thu hồi và xóa nội dung đã duyệt.",
        "permissions": [VIEW, EDIT, REVIEW, API_READ, API_WRITE],
    },
    QUERY_ROLE: {
        "description": "Truy vấn semantic layer trên những dataset user được quyền đọc trong Superset.",
        "permissions": [QUERY, API_READ, API_WRITE],
    },
}
TEXT_TO_BI_PERMISSIONS = [VIEW, EDIT, REVIEW, QUERY]
# Superset synchronizes these built-in roles and can grant them non-admin-only permissions.
BUILT_IN_ROLES = ("Alpha", "Gamma", "Public", "sql_lab")


class RoleService:
    def __init__(self, session: Session) -> None:
        self.repository = RoleRepository(session)

    # -------------------------READ---------------------------
    def get_role(self, role_id: int) -> Role | None:
        return self.repository.read_by_id(role_id)

    def role_by_name(self, name: str) -> Role | None:
        return self.repository.read_by_name(name)

    def roles(self) -> list[Role]:
        return self.repository.read_all()

    def text_to_bi_role_options(self) -> list[dict[str, str]]:
        return [{"name": name, "description": role["description"]} for name, role in TEXT_TO_BI_ROLES.items()]

    def role_assignment(self, user: Any) -> dict[str, Any]:
        role_names = [role.name for role in user.roles]
        return {
            "user_id": user.id,
            "username": user.username,
            "name": UserService.user_display_name(user),
            "is_admin": ADMIN_ROLE in role_names,
            "roles": [name for name in TEXT_TO_BI_ROLES if name in role_names],
            "other_roles": [name for name in role_names if name not in TEXT_TO_BI_ROLES],
        }

    # -------------------------CREATE/UPDATE------------------
    def ensure_text_to_bi_roles(self) -> None:
        declare_admin_only_view_menu(TEXT_TO_BI_VIEW_MENU)
        for role_name, definition in TEXT_TO_BI_ROLES.items():
            ensure_role(role_name, definition["permissions"])
        ensure_role(ADMIN_ROLE, TEXT_TO_BI_PERMISSIONS)
        for role_name in BUILT_IN_ROLES:
            revoke_permissions(role_name, TEXT_TO_BI_PERMISSIONS)

    def assign_text_to_bi_roles(self, user: Any, role_names: list[str]) -> None:
        checked_names = self.checked_role_names(role_names)
        roles = [require_role(name) for name in checked_names]
        replace_user_roles(user, TEXT_TO_BI_ROLES, roles)

    def assign_user_roles(self, user: Any, role_ids: list[int]) -> None:
        unique_ids = list(dict.fromkeys(role_ids))
        roles = [self.repository.read_by_id(role_id) for role_id in unique_ids]
        if any(role is None for role in roles):
            raise RoleAssignmentError()
        user.roles = roles

    @staticmethod
    def add_user_role(user: Any, role: Role) -> None:
        if all(existing.id != role.id for existing in user.roles):
            user.roles = [*user.roles, role]

    @staticmethod
    def remove_user_role(user: Any, role: Role) -> None:
        user.roles = [existing for existing in user.roles if existing.id != role.id]

    @staticmethod
    def user_roles(user: Any) -> dict[str, Any]:
        roles = sorted(user.roles, key=lambda item: item.name)
        return {
            "user_id": user.id,
            "username": user.username,
            "role_ids": [role.id for role in roles],
            "roles": [role.name for role in roles],
        }

    @staticmethod
    def checked_role_names(role_names: list[str]) -> list[str]:
        if not all(name in TEXT_TO_BI_ROLES for name in role_names):
            raise RoleAssignmentError()
        return list(dict.fromkeys(role_names))


def _role_service() -> RoleService:
    from ..dependencies import role_service

    return role_service()


def ensure_text_to_bi_roles() -> None:
    _role_service().ensure_text_to_bi_roles()


def declare_text_to_bi_admin_only() -> None:
    declare_admin_only_view_menu(TEXT_TO_BI_VIEW_MENU)
    declare_admin_only_view_menu(API_CLASS_PERMISSION)


def text_to_bi_role_options() -> list[dict[str, str]]:
    return _role_service().text_to_bi_role_options()


def checked_role_names(role_names: list[str]) -> list[str]:
    return RoleService.checked_role_names(role_names)


def assign_text_to_bi_roles(user: Any, role_names: list[str]) -> None:
    _role_service().assign_text_to_bi_roles(user, role_names)


def role_assignment(user: Any) -> dict[str, Any]:
    return _role_service().role_assignment(user)


def assign_user_roles(user: Any, role_ids: list[int]) -> None:
    _role_service().assign_user_roles(user, role_ids)


def add_user_role(user: Any, role: Role) -> None:
    RoleService.add_user_role(user, role)


def remove_user_role(user: Any, role: Role) -> None:
    RoleService.remove_user_role(user, role)


def user_roles(user: Any) -> dict[str, Any]:
    return RoleService.user_roles(user)


def get_role(role_id: int) -> Role | None:
    return _role_service().get_role(role_id)
