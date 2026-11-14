from ...common.exceptions import AgentError, NotFoundError, ValidationError


class AgentLadderValidationError(ValidationError):
    pass


class ProposalAlreadyReviewedError(ValidationError):
    message = "Đề xuất này đã được xử lý."


class TooManyPendingProposalsError(AgentError):
    status = 429
    message = "Đã có quá nhiều đề xuất dataset đang chờ duyệt."


class DatasetProposalNotFoundError(NotFoundError):
    message = "Dataset proposal not found."
