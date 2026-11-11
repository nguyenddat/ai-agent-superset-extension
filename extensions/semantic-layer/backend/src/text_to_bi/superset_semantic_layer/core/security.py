from functools import wraps
from typing import Any

from flask import current_app, request
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
from superset import security_manager
from superset.exceptions import SupersetSecurityException
from wtforms import ValidationError

from .exceptions import (
    AdminRequiredError,
    CsrfTokenError,
    DatasetAccessError,
    SemanticLayerQueryRequiredError,
    SemanticLayerViewRequiredError,
)

# The FAB view menu and permissions behind the Semantic Layer's roles (modules/access_control). Superset's own role
# sync must never hand them to Alpha or Gamma, so access_control declares this view menu admin-only.
SEMANTIC_LAYER_VIEW_MENU = "Text to BI Semantic Layer"
VIEW_PERMISSION = "can_view"
QUERY_PERMISSION = "can_query"


def is_admin() -> bool:
    return bool(
        getattr(current_user, "is_authenticated", False)
        and any(role.name == "Admin" for role in getattr(current_user, "roles", []))
    )


def require_admin() -> None:
    if not is_admin():
        raise AdminRequiredError()


def has_semantic_layer_permission(permission: str) -> bool:
    """Whether the signed-in user holds a Semantic Layer permission through any of their Superset roles."""
    if not getattr(current_user, "is_authenticated", False):
        return False
    return bool(security_manager.can_access(permission, SEMANTIC_LAYER_VIEW_MENU))


def can_view_semantic_layer() -> bool:
    """Read the governed content: the Semantic Layer page and its read-only routes."""
    return is_admin() or has_semantic_layer_permission(VIEW_PERMISSION)


def can_query_semantic_layer() -> bool:
    """Read the consumer catalog and run approved metrics, as the AI Agent does on the user's behalf."""
    return is_admin() or has_semantic_layer_permission(QUERY_PERMISSION)


def require_semantic_layer_view() -> None:
    if not can_view_semantic_layer():
        raise SemanticLayerViewRequiredError()


def require_semantic_layer_query() -> None:
    if not can_query_semantic_layer():
        raise SemanticLayerQueryRequiredError()


def can_access_dataset(dataset: Any) -> bool:
    """Whether the signed-in user may read this dataset, by Superset's own datasource permission check."""
    try:
        security_manager.raise_for_access(datasource=dataset)
    except SupersetSecurityException:
        return False
    return True


def require_dataset_access(dataset: Any) -> None:
    if not can_access_dataset(dataset):
        raise DatasetAccessError()


def csrf_protected(method):
    """Reject a state-changing request that does not carry a valid CSRF token."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            error = CsrfTokenError()
            return self.response(error.status, message=str(error))
        return method(self, *args, **kwargs)

    return wrapper


def is_superset_access_error(error: Exception) -> bool:
    return any(word in error.__class__.__name__.lower() for word in ("access", "forbidden", "permission", "security"))


def second_reviewer_required() -> bool:
    """Whether a proposal's author must leave its approval to another administrator.

    Off by default so a single administrator can approve their own work; a deployment with several reviewers
    sets TEXT_TO_BI_REQUIRE_SECOND_REVIEWER = True in superset_config.
    """
    return bool(current_app.config.get("TEXT_TO_BI_REQUIRE_SECOND_REVIEWER", False))


