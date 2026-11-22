from text_to_bi.superset_text_to_bi.common.base_exceptions import ConflictError, NotFoundError, ValidationError


class ExpertRuleNotFoundError(NotFoundError):
    code = "expert_rule_not_found"
    message = "Không tìm thấy quy tắc."


class ExpertRuleValidationError(ValidationError):
    code = "expert_rule_validation_error"
    message = "Quy tắc không hợp lệ."


class ExpertRuleConflictError(ConflictError):
    code = "expert_rule_conflict"
    message = "Quy tắc đã thay đổi; tải lại rồi thử lại."
