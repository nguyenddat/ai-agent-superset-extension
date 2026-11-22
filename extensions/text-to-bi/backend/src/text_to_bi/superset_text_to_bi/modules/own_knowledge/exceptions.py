from text_to_bi.superset_text_to_bi.common.base_exceptions import ConflictError, NotFoundError, ValidationError


class OwnKnowledgeValidationError(ValidationError):
    code = "own_knowledge_invalid"
    message = "Dữ liệu own knowledge không hợp lệ."


class OwnKnowledgeConflictError(ConflictError):
    code = "own_knowledge_conflict"
    message = "Dữ liệu đã thay đổi; hãy tải lại trước khi lưu."


class OwnKnowledgeNotFoundError(NotFoundError):
    code = "own_knowledge_not_found"
    message = "Không tìm thấy nội dung own knowledge."
