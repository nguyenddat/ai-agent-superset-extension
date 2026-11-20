from ...common.exceptions import NotFoundError, ValidationError


class QuestionHandlingValidationError(ValidationError):
    pass


class QuestionNotFoundError(NotFoundError):
    message = "Không tìm thấy câu hỏi."
