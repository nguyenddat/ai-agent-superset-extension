from text_to_bi.superset_semantic_layer.common.exceptions import (
    ConflictError,
    NotAuthorizedError,
    NotFoundError,
    SelfApprovalError,
    TooManyRequestsError,
    ValidationError,
)


class MetricContractValidationError(ValidationError):
    """A metric contract, its review or its business definition breaks a rule."""


class MetricDefinitionNotFoundError(NotFoundError):
    message = "Metric này chưa có định nghĩa nghiệp vụ."


class MetricContractNotFoundError(NotFoundError):
    message = "Metric này chưa được đề xuất trong dataset."


class ApprovedMetricContractRequiredError(NotAuthorizedError):
    message = "Metric chưa được duyệt, hoặc đã đổi sau lần duyệt, nên chưa chạy được."


class ApprovedMetricDatasetRequiredError(NotAuthorizedError):
    message = "Dataset chưa có metric nào được duyệt."


class MetricSelfApprovalError(SelfApprovalError):
    message = "Người đề xuất không thể tự duyệt; cần một quản trị viên khác duyệt."


class MetricExecutionDeniedError(NotAuthorizedError):
    message = "Superset không cho bạn chạy metric này."


class ApprovedMetricContractExistsError(ConflictError):
    message = "Thu hồi bản đã duyệt trước khi tạo bản đề xuất mới."


class AggregateDatasetRequiredError(ValidationError):
    message = "AI Agent chỉ tạo metric trên dataset tổng hợp (aggregate)."


class AgentMetricRevokedError(ConflictError):
    message = "Một metric cùng công thức đã bị quản trị viên thu hồi."


class AgentMetricPendingError(ConflictError):
    message = "Một metric cùng công thức đang chờ quản trị viên xử lý."


class TooManyPendingAgentMetricsError(TooManyRequestsError):
    message = "Dataset này có quá nhiều metric AI Agent đang chờ duyệt."
