class AgentError(Exception):
    abstract = True
    status = 400
    message = "Yêu cầu không hợp lệ."

    def __new__(cls, *args, **kwargs):
        if cls.__dict__.get("abstract", False):
            raise TypeError(f"{cls.__name__} is abstract; raise a module's own subclass.")
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, message: str | None = None) -> None:
        super().__init__(self.message if message is None else message)


class ValidationError(AgentError, ValueError):
    abstract = True
    status = 400
    message = "Dữ liệu gửi lên không hợp lệ."


class NotAuthorizedError(AgentError):
    abstract = True
    status = 403
    message = "Không có quyền thực hiện thao tác này."


class NotFoundError(AgentError):
    abstract = True
    status = 404
    message = "Không tìm thấy dữ liệu."


class ServiceUnavailableError(AgentError):
    abstract = True
    status = 503
    message = "Dịch vụ tạm thời không sẵn sàng."
