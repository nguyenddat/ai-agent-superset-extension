from collections.abc import Iterable
from typing import Any

from superset import security_manager

from ..exceptions import RoleNotFoundError

# A (permission, view menu) pair, as Flask-AppBuilder stores it: ("can_read", "text_to_bi_semantic_layer_api").
Permission = tuple[str, str]


def declare_admin_only_view_menu(view_menu_name: str) -> None:
    """Keep Superset's role sync (`superset init`) from handing this view menu's permissions to Alpha or Gamma.

    Superset gives its built-in roles every permission not listed as admin-only; the set is extended on this security
    manager only, so the declaration lasts for the process that loaded the extension.
    """
    admin_only = security_manager.ADMIN_ONLY_VIEW_MENUS
    if view_menu_name not in admin_only:
        security_manager.ADMIN_ONLY_VIEW_MENUS = {*admin_only, view_menu_name}


def ensure_role(role_name: str, permissions: Iterable[Permission]) -> Any:
    """The role with this name, created when missing and given each permission it lacks; it keeps any others."""
    role = security_manager.add_role(role_name)
    for permission_name, view_menu_name in permissions:
        permission_view = security_manager.add_permission_view_menu(permission_name, view_menu_name)
        security_manager.add_permission_role(role, permission_view)
    return role


def revoke_permissions(role_name: str, permissions: Iterable[Permission]) -> None:
    """Take these permissions away from a role, if the role exists and holds them."""
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
    """Drop the user's roles named in `removed_role_names` and add `added_roles`; their other roles stay."""
    removed = set(removed_role_names)
    kept = [role for role in user.roles if role.name not in removed]
    user.roles = kept + [role for role in added_roles if role not in kept]
