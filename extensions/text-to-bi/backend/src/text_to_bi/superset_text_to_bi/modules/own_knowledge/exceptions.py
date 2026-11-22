from text_to_bi.superset_text_to_bi.common.base_exceptions import NotFoundError, ValidationError


class UserDefinitionNotFoundError(NotFoundError):
    code = "user_definition_not_found"
    message = "Không tìm thấy định nghĩa cá nhân."


class UserDefinitionValidationError(ValidationError):
    code = "user_definition_validation_error"
    message = "Định nghĩa cá nhân không hợp lệ."
