from ...common.exceptions import NotFoundError, ValidationError


class QueryDatasetNotFoundError(NotFoundError):
    message = "Không tìm thấy dataset hoặc bạn không có quyền truy vấn dataset này."


class QueryDatabaseIdRequiredError(ValidationError):
    message = "database_id is required."


class ApprovedMetricDatasetRequiredError(ValidationError):
    message = "Cần dataset tổng hợp hoặc dataset có metric đã duyệt còn hiệu lực."
