from text_to_bi.superset_text_to_bi.common.base_exceptions import NotFoundError, ValidationError


class DataLineageValidationError(ValidationError):
    code = "data_lineage_validation_error"


class LineageDatabaseNotFoundError(NotFoundError):
    code = "lineage_database_not_found"
    message = "Không tìm thấy database được yêu cầu."
