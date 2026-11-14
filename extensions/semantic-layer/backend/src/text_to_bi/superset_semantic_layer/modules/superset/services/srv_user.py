# pyright: reportAbstractUsage=false

from collections.abc import Callable
from typing import Any

from superset_core.common import daos

from ..exceptions import UserNotFoundError


def get_user(user_id: int) -> Any | None:
    return daos.UserDAO.find_one_or_none(id=user_id)

def require_user(user_id: int) -> Any:
    user = get_user(user_id)
    if user is None:
        raise UserNotFoundError()
    return user

def active_users() -> list[Any]:
    return sorted(daos.UserDAO.filter_by(active=True), key=lambda user: user.username or "")


def user_names() -> Callable[[int | None], str | None]:
    names: dict[int, str | None] = {}
    def user_name(user_id: int | None) -> str | None:
        if user_id is None:
            return None
        if user_id not in names:
            user = get_user(user_id)
            names[user_id] = (user.get_full_name().strip() or user.username) if user else None
        return names[user_id]
    return user_name
