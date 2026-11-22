from text_to_bi.superset_text_to_bi.common.base_exceptions import NotFoundError


class DatasetNotFoundError(NotFoundError):
    code = "dataset_not_found"
    message = "Không tìm thấy dataset được yêu cầu."


class UserNotFoundError(NotFoundError):
    code = "user_not_found"
    message = "Không tìm thấy người dùng."


class RoleNotFoundError(NotFoundError):
    code = "role_not_found"
    message = "Không tìm thấy nhóm quyền trong Superset."
