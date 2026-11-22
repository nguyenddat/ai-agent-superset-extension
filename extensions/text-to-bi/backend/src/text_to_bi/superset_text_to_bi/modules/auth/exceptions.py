from text_to_bi.superset_text_to_bi.common.base_exceptions import (
    NotAuthenticatedError,
    NotAuthorizedError,
    ValidationError,
)


class SignInRequiredError(NotAuthenticatedError):
    code = "sign_in_required"


class AdminRequiredError(NotAuthorizedError):
    code = "admin_required"
    message = "Chỉ quản trị viên được thực hiện thao tác này."


class ViewRequiredError(NotAuthorizedError):
    code = "view_permission_required"
    message = "Bạn chưa có quyền xem Text to BI. Hãy nhờ quản trị viên gán nhóm quyền Text to BI Viewer."


class EditRequiredError(NotAuthorizedError):
    code = "edit_permission_required"
    message = "Bạn chưa có quyền sửa Text to BI. Hãy nhờ quản trị viên gán nhóm quyền Text to BI Editor."


class QueryRequiredError(NotAuthorizedError):
    code = "query_permission_required"
    message = "Bạn chưa có quyền hỏi dữ liệu. Hãy nhờ quản trị viên gán nhóm quyền Text to BI Query."


class DatasetAccessError(NotAuthorizedError):
    code = "dataset_access_required"
    message = "Bạn không có quyền đọc dataset này hoặc database của nó trong Superset."


class RoleAssignmentError(ValidationError):
    code = "invalid_role_assignment"
    message = "Danh sách nhóm quyền không hợp lệ: chỉ gửi tên nhóm quyền của Text to BI."
