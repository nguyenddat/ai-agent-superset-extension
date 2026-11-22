from text_to_bi.superset_text_to_bi.common.base_exceptions import ConflictError, NotFoundError, ValidationError


class DataLineageValidationError(ValidationError):
    code = "data_lineage_validation_error"


class LineageDatabaseNotFoundError(NotFoundError):
    code = "lineage_database_not_found"
    message = "Không tìm thấy database được yêu cầu."


class LineageNotFoundError(NotFoundError):
    code = "lineage_transformation_not_found"
    message = "Không tìm thấy phép biến đổi lineage."


class LineageConflictError(ConflictError):
    code = "lineage_transformation_conflict"
    message = "Tên phép biến đổi đã tồn tại trên dataset đích."
