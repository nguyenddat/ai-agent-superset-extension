from functools import wraps

from flask import request
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
from wtforms import ValidationError

from .exceptions import AdminRequiredError, CsrfTokenError, SemanticLayerQueryRequiredError

# The Semantic Layer extension owns this FAB view menu and grants `can_query` on it through its "Semantic Layer Query"
# role; the names must match its core/security.py.
SEMANTIC_LAYER_VIEW_MENU = "Text to BI Semantic Layer"
QUERY_PERMISSION = "can_query"


def is_admin() -> bool:
    return bool(
        getattr(current_user, "is_authenticated", False)
        and any(role.name == "Admin" for role in getattr(current_user, "roles", []))
    )


def require_admin() -> None:
    if not is_admin():
        raise AdminRequiredError()


def can_query_semantic_layer() -> bool:
    if is_admin():
        return True
    if not getattr(current_user, "is_authenticated", False):
        return False
    from superset import security_manager

    return bool(security_manager.can_access(QUERY_PERMISSION, SEMANTIC_LAYER_VIEW_MENU))


def require_semantic_layer_query() -> None:
    if not can_query_semantic_layer():
        raise SemanticLayerQueryRequiredError()


def csrf_protected(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            error = CsrfTokenError()
            return self.response(error.status, message=str(error))
        return method(self, *args, **kwargs)

    return wrapper
