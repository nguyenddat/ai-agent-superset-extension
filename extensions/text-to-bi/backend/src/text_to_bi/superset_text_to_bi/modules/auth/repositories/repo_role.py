from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Role


class RoleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -------------------------READ---------------------------
    def read_by_id(self, role_id: int) -> Role | None:
        return self.session.get(Role, role_id)

    def read_by_name(self, name: str) -> Role | None:
        return self.session.scalar(select(Role).where(Role.name == name))

    def read_by_names(self, names: Iterable[str]) -> list[Role]:
        requested = list(dict.fromkeys(names))
        if not requested:
            return []
        statement = select(Role).where(Role.name.in_(requested)).order_by(Role.name)
        return list(self.session.scalars(statement).all())

    def read_all(self) -> list[Role]:
        return list(self.session.scalars(select(Role).order_by(Role.name)).all())
