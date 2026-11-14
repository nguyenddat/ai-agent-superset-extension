from collections.abc import Iterable
from typing import Any

from superset import security_manager

from ..exceptions import RoleNotFoundError

Permission = tuple[str, str]

def declare_admin_only_view_menu(view_menu_name: str) -> None:
    admin_only = security_manager.ADMIN_ONLY_VIEW_MENUS
    if view_menu_name not in admin_only:
        security_manager.ADMIN_ONLY_VIEW_MENUS = {*admin_only, view_menu_name}

def ensure_role(role_name: str, permissions: Iterable[Permission]) -> Any:
    role = security_manager.add_role(role_name)
    for permission_name, view_menu_name in permissions:
        permission_view = security_manager.add_permission_view_menu(permission_name, view_menu_name)
        security_manager.add_permission_role(role, permission_view)
    return role

def revoke_permissions(role_name: str, permissions: Iterable[Permission]) -> None:
    role = security_manager.find_role(role_name)
    if role is None:
        return
    for permission_name, view_menu_name in permissions:
        permission_view = security_manager.find_permission_view_menu(permission_name, view_menu_name)
        if permission_view is not None:
            security_manager.del_permission_role(role, permission_view)

def require_role(role_name: str) -> Any:
    role = security_manager.find_role(role_name)
    if role is None:
        raise RoleNotFoundError()
    return role

def replace_user_roles(user: Any, removed_role_names: Iterable[str], added_roles: Iterable[Any]) -> None:
    removed = set(removed_role_names)
    kept = [role for role in user.roles if role.name not in removed]
    user.roles = kept + [role for role in added_roles if role not in kept]
