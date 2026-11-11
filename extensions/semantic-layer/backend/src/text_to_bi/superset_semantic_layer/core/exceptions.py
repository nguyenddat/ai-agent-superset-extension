from ..common.exceptions import NotAuthorizedError, ValidationError


class AdminRequiredError(NotAuthorizedError):
    message = "Admin access required."


class SemanticLayerViewRequiredError(NotAuthorizedError):
    message = "Bạn chưa có quyền xem Semantic Layer. Hãy nhờ quản trị viên gán nhóm quyền Semantic Layer Viewer."


class SemanticLayerQueryRequiredError(NotAuthorizedError):
    message = "Bạn chưa có quyền truy vấn Semantic Layer. Hãy nhờ quản trị viên gán nhóm quyền Semantic Layer Query."


class DatasetAccessError(NotAuthorizedError):
    message = "Dataset and database access required."


class CsrfTokenError(NotAuthorizedError):
    message = "CSRF token không hợp lệ."


class DatasetIdRequiredError(ValidationError):
    message = "dataset_id is required."


class DatabaseIdRequiredError(ValidationError):
    message = "database_id is required."


class RequestBodyError(ValidationError):
    message = "Request body must be a JSON object."
