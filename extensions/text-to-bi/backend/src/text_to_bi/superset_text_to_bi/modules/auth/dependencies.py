from superset.extensions import db

from .services import UserService


def user_service() -> UserService:
    return UserService(db.session)
