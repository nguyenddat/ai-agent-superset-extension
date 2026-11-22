from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -------------------------READ---------------------------
    def read_by_id(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def read_active(self) -> list[User]:
        statement = select(User).where(User.active.is_(True)).order_by(User.username)
        return list(self.session.scalars(statement).all())
