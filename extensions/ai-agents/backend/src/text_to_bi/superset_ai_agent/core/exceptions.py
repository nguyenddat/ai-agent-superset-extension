from ..common.exceptions import NotAuthorizedError, ServiceUnavailableError


class AdminRequiredError(NotAuthorizedError):
    message = "Admin access required."


class CsrfTokenError(NotAuthorizedError):
    message = "CSRF token không hợp lệ."


class SemanticLayerQueryRequiredError(NotAuthorizedError):
    message = "Bạn chưa có quyền truy vấn Semantic Layer. Hãy nhờ quản trị viên gán nhóm quyền Semantic Layer Query."


class ChatModelNotConfiguredError(ServiceUnavailableError):
    message = (
        "OPENROUTER_API_KEY chưa được cấu hình. Đặt biến này trong file .env ở thư mục gốc repo "
        "rồi khởi động lại dịch vụ superset."
    )
