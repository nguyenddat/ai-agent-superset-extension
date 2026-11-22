from typing import Any

from flask import has_request_context
from flask_login import current_user


def request_user() -> Any | None:
    if not has_request_context() or not getattr(current_user, "is_authenticated", False):
        return None
    return current_user


# The signed-in Superset user's ab_user.id; None outside a request or for an anonymous caller.
def request_user_id() -> int | None:
    user = request_user()
    user_id = getattr(user, "id", None)
    return None if user_id is None else int(user_id)
