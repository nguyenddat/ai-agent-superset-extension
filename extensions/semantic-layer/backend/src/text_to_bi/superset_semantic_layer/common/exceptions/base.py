class SemanticLayerError(Exception):
    abstract = True
    status = 400
    message = "Yêu cầu không hợp lệ."

    def __new__(cls, *args, **kwargs):
        if cls.__dict__.get("abstract", False):
            raise TypeError(f"{cls.__name__} is abstract; raise a module's own subclass.")
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, message: str | None = None) -> None:
        super().__init__(self.message if message is None else message)


class ValidationError(SemanticLayerError, ValueError):
    abstract = True
    status = 400
    message = "Dữ liệu gửi lên không hợp lệ."


class NotAuthorizedError(SemanticLayerError):
    abstract = True
    status = 403
    message = "Không có quyền thực hiện thao tác này."


class SelfApprovalError(NotAuthorizedError):
    abstract = True
    message = "Người soạn không thể tự duyệt; cần một quản trị viên khác duyệt."


class NotFoundError(SemanticLayerError):
    abstract = True
    status = 404
    message = "Không tìm thấy dữ liệu."


class ConflictError(SemanticLayerError):
    abstract = True
    status = 409
    message = "Dữ liệu đã thay đổi; tải lại rồi thử lại."


class TooManyRequestsError(SemanticLayerError):
    abstract = True
    status = 429
    message = "Có quá nhiều yêu cầu đang chờ xử lý."


class ServiceUnavailableError(SemanticLayerError):
    abstract = True
    status = 503
    message = "Dịch vụ tạm thời không sẵn sàng."
