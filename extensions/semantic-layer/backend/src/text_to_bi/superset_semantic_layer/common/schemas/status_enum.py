from enum import Enum


class ReviewStatus(str, Enum):
    """Trạng thái duyệt chung của metric, thuật ngữ và quy tắc chuyên gia."""

    DRAFT = "draft"
    APPROVED = "approved"
    REVOKED = "revoked"

    @classmethod
    def check(cls, column: str = "status") -> str:
        return f"{column} IN (" + ", ".join(f"'{status.value}'" for status in cls) + ")"
