from ...common.exceptions import NotAuthorizedError, ValidationError


class GoalError(ValidationError):
    pass


class NoJoinPathError(ValidationError):
    message = "No approved relationships connect every needed table."

    def __init__(self, unreachable: list[int]) -> None:
        super().__init__()
        self.unreachable = unreachable


class AnalysisLabAdminRequiredError(NotAuthorizedError):
    message = "Chỉ quản trị viên dùng được phòng thử phân tích."


class DatabaseIdRequiredError(ValidationError):
    message = "Cần database_id."
