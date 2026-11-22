from text_to_bi.superset_text_to_bi.common.base_exceptions import ConflictError, NotFoundError, ValidationError


class ConversationValidationError(ValidationError):
    code = "conversation_invalid"
    message = "Dữ liệu hội thoại không hợp lệ."


class ConversationNotFoundError(NotFoundError):
    code = "conversation_not_found"
    message = "Không tìm thấy hội thoại."


class ConversationTurnNotFoundError(NotFoundError):
    code = "conversation_turn_not_found"
    message = "Không tìm thấy lượt hỏi đáp."


class ConversationDatabaseNotFoundError(NotFoundError):
    code = "conversation_database_not_found"
    message = "Database Superset không tồn tại hoặc không có quyền truy cập."


class ConversationTurnNotContinuableError(ConflictError):
    code = "conversation_turn_not_continuable"
    message = "Lượt hỏi đáp này không chờ người dùng trả lời nên không tiếp tục được."


class ConversationResultNotFoundError(NotFoundError):
    code = "conversation_result_not_found"
    message = "Không tìm thấy kết quả này trong lượt hỏi đáp."


class ConversationChartInvalidError(ValidationError):
    code = "conversation_chart_invalid"
    message = "Biểu đồ không hợp lệ."
