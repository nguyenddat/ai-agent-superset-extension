from text_to_bi.superset_semantic_layer.common.exceptions import ConflictError, NotFoundError, SelfApprovalError, ServiceUnavailableError, ValidationError


# -------------------------DICTIONARY---------------------
class DataDictionaryValidationError(ValidationError):
    """Dictionary metadata or time semantics that breaks a rule."""


class NoColumnsToDescribeError(ValidationError):
    message = "Dataset has no columns to describe."


class ReferencedColumnMissingError(ValidationError):
    message = "Referenced column no longer exists."


class TransformationSourceMissingError(ValidationError):
    message = "Cột nguồn của phép biến đổi không còn tồn tại."


class SuggestionInProgressError(ConflictError):
    message = "Dataset này đang được AI gợi ý, vui lòng đợi hoàn tất."


class AutoFillUnavailableError(ServiceUnavailableError):
    message = "AI AutoFill chưa sẵn sàng."


# -------------------------RELATIONSHIP-------------------
class RelationshipValidationError(ValidationError):
    """A relationship between datasets, or its contract, breaks a rule."""


class RelationshipSelfApprovalError(SelfApprovalError):
    message = "Người soạn quan hệ không thể tự duyệt; cần một quản trị viên khác duyệt."


class ForeignKeyColumnNotFoundError(NotFoundError):
    message = "Foreign-key dictionary column not found in this dataset."


class RelationshipContractNotFoundError(NotFoundError):
    message = "Relationship contract not found for this foreign key."


class RelationshipCandidateRequiredError(NotFoundError):
    message = "Create a candidate contract before checking the data."


class ApprovedContractExistsError(ConflictError):
    message = "Thu hồi bản đã duyệt trước khi tạo bản đề xuất mới."


class DatasetDraftValidationError(ValidationError):
    """A submitted dataset or metric draft breaks the metadata rules."""


class ProposedDatasetCreationError(ValidationError):
    message = "Superset không chạy được câu SQL để đọc các cột của dataset."
