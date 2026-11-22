from text_to_bi.superset_text_to_bi.common.base_exceptions import ConflictError, NotFoundError, ValidationError


class GlossaryNotFoundError(NotFoundError):
    code = "glossary_not_found"
    message = "Không tìm thấy thuật ngữ."


class GlossaryValidationError(ValidationError):
    code = "glossary_validation_error"
    message = "Thuật ngữ không hợp lệ."


class GlossaryConflictError(ConflictError):
    code = "glossary_conflict"
    message = "Thuật ngữ đã thay đổi; tải lại rồi thử lại."
