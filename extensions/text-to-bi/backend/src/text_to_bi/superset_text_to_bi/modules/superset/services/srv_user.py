from text_to_bi.superset_text_to_bi.modules.auth.dependencies import user_service
from text_to_bi.superset_text_to_bi.modules.auth.models import User
from text_to_bi.superset_text_to_bi.modules.auth.services import UserService


def get_user(user_id: int) -> User | None:
    return user_service().get_user(user_id)


def require_user(user_id: int) -> User:
    return user_service().require_user(user_id)


def active_users() -> list[User]:
    return user_service().active_users()


def user_display_name(user: User) -> str:
    return UserService.user_display_name(user)
