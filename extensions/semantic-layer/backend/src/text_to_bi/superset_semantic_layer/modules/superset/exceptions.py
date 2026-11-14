from ...common.exceptions import NotFoundError


class DatasetNotFoundError(NotFoundError):
    message = "Dataset not found."


class DatasetMetricNotFoundError(NotFoundError):
    message = "Không tìm thấy metric này trong dataset."


class DatabaseNotFoundError(NotFoundError):
    message = "Database not found."


class UserNotFoundError(NotFoundError):
    message = "Không tìm thấy người dùng."


class RoleNotFoundError(NotFoundError):
    message = "Không tìm thấy nhóm quyền trong Superset."
