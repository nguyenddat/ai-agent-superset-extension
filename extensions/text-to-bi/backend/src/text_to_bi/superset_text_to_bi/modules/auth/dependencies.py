from superset.extensions import db

from .services import RoleService, UserService


def role_service() -> RoleService:
    return RoleService(db.session)


def user_service() -> UserService:
    return UserService(db.session)
