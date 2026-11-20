from ...common.exceptions import NotFoundError, ValidationError


class UserDefinitionValidationError(ValidationError):
    pass


class UserDefinitionNotFoundError(NotFoundError):
    message = "Không tìm thấy định nghĩa."


class DashboardIdRequiredError(ValidationError):
    message = "Cần dashboard_id."
