from text_to_bi.superset_text_to_bi.common.base_exceptions import NotAuthorizedError, ValidationError


class CsrfTokenError(NotAuthorizedError):
    code = "csrf_token_invalid"
    message = "CSRF token không hợp lệ."


class RequestBodyError(ValidationError):
    code = "invalid_request"
    message = "Dữ liệu yêu cầu không hợp lệ."


class QueryParameterError(ValidationError):
    code = "invalid_query_parameter"
    message = "Tham số truy vấn không hợp lệ."
