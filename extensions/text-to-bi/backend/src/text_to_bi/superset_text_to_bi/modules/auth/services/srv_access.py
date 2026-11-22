from typing import Any

from superset.extensions import security_manager

from text_to_bi.superset_text_to_bi.common.utils.request_user import request_user
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import can_access_dataset

from ..exceptions import (
    AdminRequiredError,
    DatasetAccessError,
    EditRequiredError,
    QueryRequiredError,
    ReviewRequiredError,
    SignInRequiredError,
    ViewRequiredError,
)

# The FAB view menu behind the extension's roles. It is declared admin-only (srv_roles), so Superset's role sync never
# hands its permissions to Alpha or Gamma.
TEXT_TO_BI_VIEW_MENU = "Text to BI"
VIEW_PERMISSION = "can_view"
EDIT_PERMISSION = "can_edit"
QUERY_PERMISSION = "can_query"
REVIEW_PERMISSION = "can_review"
ADMIN_ROLE = "Admin"


def current_user() -> Any:
    user = request_user()
    if user is None:
        raise SignInRequiredError()
    return user


def current_user_id() -> int:
    return int(current_user().id)


def is_admin() -> bool:
    user = request_user()
    return user is not None and any(role.name == ADMIN_ROLE for role in getattr(user, "roles", []))


def has_permission(permission_name: str) -> bool:
    return request_user() is not None and bool(security_manager.can_access(permission_name, TEXT_TO_BI_VIEW_MENU))


def can_view() -> bool:
    return is_admin() or has_permission(VIEW_PERMISSION)


def can_edit_datasets() -> bool:
    return is_admin() or has_permission(EDIT_PERMISSION)


def can_query_datasets() -> bool:
    return is_admin() or has_permission(QUERY_PERMISSION)


def can_review_semantic_layer() -> bool:
    return is_admin() or has_permission(REVIEW_PERMISSION)


# Superset's own dataset access applies on top of every Text to BI role, the Admin included.
def can_edit(dataset: Any) -> bool:
    return can_edit_datasets() and can_access_dataset(dataset)


def require_admin() -> None:
    if not is_admin():
        raise AdminRequiredError()


def require_review() -> None:
    if not can_review_semantic_layer():
        raise ReviewRequiredError()


def require_view() -> None:
    if not can_view():
        raise ViewRequiredError()


def require_dataset_access(dataset: Any) -> None:
    if not can_access_dataset(dataset):
        raise DatasetAccessError()


def require_edit(dataset: Any) -> None:
    if not can_edit_datasets():
        raise EditRequiredError()
    require_dataset_access(dataset)


def require_query(dataset: Any) -> None:
    if not can_query_datasets():
        raise QueryRequiredError()
    require_dataset_access(dataset)
