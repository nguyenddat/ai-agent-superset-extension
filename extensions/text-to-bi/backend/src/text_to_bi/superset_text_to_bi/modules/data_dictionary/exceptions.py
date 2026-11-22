from text_to_bi.superset_text_to_bi.common.base_exceptions import (
    BadGatewayError,
    ConflictError,
    ServiceUnavailableError,
    ValidationError,
)


class DataDictionaryValidationError(ValidationError):
    code = "invalid_data_dictionary"
    message = "Từ điển dữ liệu không hợp lệ."


class DictionaryAutofillUnavailableError(ServiceUnavailableError):
    code = "dictionary_autofill_unavailable"
    message = "Tự động điền chưa sẵn sàng: chưa cấu hình OPENROUTER_API_KEY."


class DictionaryAutofillInProgressError(ConflictError):
    code = "dictionary_autofill_in_progress"
    message = "Dataset đang được tự động điền; chờ lượt hiện tại kết thúc."


class DictionaryAutofillFailedError(BadGatewayError):
    code = "dictionary_autofill_failed"
    message = "Mô hình không trả về gợi ý hợp lệ; thử lại sau."
