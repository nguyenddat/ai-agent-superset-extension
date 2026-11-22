from text_to_bi.superset_text_to_bi.common.base_exceptions import ConflictError, NotFoundError, ValidationError


class MetricNotFoundError(NotFoundError):
    code = "metric_not_found"
    message = "Không tìm thấy metric."


class MetricValidationError(ValidationError):
    code = "metric_validation_error"
    message = "Metric không hợp lệ."


class MetricConflictError(ConflictError):
    code = "metric_conflict"
    message = "Metric đã tồn tại hoặc đã thay đổi."
