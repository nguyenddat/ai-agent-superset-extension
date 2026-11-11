from ...common.exceptions import ConflictError, NotFoundError, ValidationError


class ContradictionValidationError(ValidationError):
    """A dismissal that cannot be saved as sent."""


class ContradictionNotFoundError(NotFoundError):
    message = "Không tìm thấy mâu thuẫn; bấm “Kiểm tra lại” để cập nhật danh sách."


class ContradictionCheckConflictError(ConflictError):
    message = "Một lượt kiểm tra khác vừa lưu kết quả; bấm “Kiểm tra lại”."
