from ...common.exceptions import (
    ConflictError,
    NotAuthorizedError,
    NotFoundError,
    SelfApprovalError,
    ValidationError,
)


class MetricContractValidationError(ValidationError):
    """A metric contract, its review or its business definition breaks a rule."""


class RelationshipValidationError(ValidationError):
    """A relationship between datasets, or its contract, breaks a rule."""


class MetricNotFoundError(NotFoundError):
    message = "Không tìm thấy metric này trong dataset."


class MetricContractNotFoundError(NotFoundError):
    message = "Metric này chưa được đề xuất trong dataset."


class ForeignKeyColumnNotFoundError(NotFoundError):
    message = "Foreign-key dictionary column not found in this dataset."


class RelationshipContractNotFoundError(NotFoundError):
    message = "Relationship contract not found for this foreign key."


class RelationshipCandidateRequiredError(NotFoundError):
    message = "Create a candidate contract before checking the data."


class ApprovedMetricContractRequiredError(NotAuthorizedError):
    message = "Metric chưa được duyệt, hoặc đã đổi sau lần duyệt, nên chưa chạy được."


class ApprovedMetricDatasetRequiredError(NotAuthorizedError):
    message = "Dataset chưa có metric nào được duyệt."


class MetricSelfApprovalError(SelfApprovalError):
    message = "Người đề xuất không thể tự duyệt; cần một quản trị viên khác duyệt."


class MetricExecutionDeniedError(NotAuthorizedError):
    message = "Superset không cho bạn chạy metric này."


class ApprovedContractExistsError(ConflictError):
    message = "Thu hồi bản đã duyệt trước khi tạo bản đề xuất mới."
