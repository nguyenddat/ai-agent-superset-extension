from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.modules.superset.exceptions import UserNotFoundError

from ..models import User
from ..repositories import UserRepository


class UserService:
    def __init__(self, session: Session) -> None:
        self.repository = UserRepository(session)

    # -------------------------READ---------------------------
    def get_user(self, user_id: int) -> User | None:
        return self.repository.read_by_id(user_id)

    def require_user(self, user_id: int) -> User:
        user = self.get_user(user_id)
        if user is None:
            raise UserNotFoundError()
        return user

    def active_users(self) -> list[User]:
        return self.repository.read_active()

    @staticmethod
    def user_display_name(user: User) -> str:
        return (user.get_full_name() or "").strip() or user.username
