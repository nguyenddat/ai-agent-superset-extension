from ...common.exceptions import ValidationError


class RoleAssignmentError(ValidationError):
    message = "Danh sách nhóm quyền không hợp lệ: gửi {\"roles\": [...]} với tên nhóm quyền của Semantic Layer."
