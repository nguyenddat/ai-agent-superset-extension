from text_to_bi.superset_semantic_layer.common.exceptions import (
    ConflictError,
    NotFoundError,
    SelfApprovalError,
    ValidationError,
)


class GlossaryValidationError(ValidationError):
    pass


class GlossaryConflictError(ConflictError):
    pass


class GlossarySelfApprovalError(SelfApprovalError):
    message = "Người soạn thuật ngữ không thể tự duyệt; cần một quản trị viên khác duyệt."


class GlossaryTermNotFoundError(NotFoundError):
    message = "Glossary term not found."


class GlossaryTermGroupNotFoundError(NotFoundError):
    message = "Không tìm thấy nhóm thuật ngữ."


class ContradictionValidationError(ValidationError):
    pass


class ContradictionNotFoundError(NotFoundError):
    message = "Không tìm thấy mâu thuẫn; bấm “Kiểm tra lại” để cập nhật danh sách."


class ContradictionCheckConflictError(ConflictError):
    message = "Một lượt kiểm tra khác vừa lưu kết quả; bấm “Kiểm tra lại”."
