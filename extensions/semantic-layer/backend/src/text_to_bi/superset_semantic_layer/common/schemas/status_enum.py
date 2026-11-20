from enum import Enum


class ReviewStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REVOKED = "revoked"

    @classmethod
    def check(cls, column: str = "status") -> str:
        return f"{column} IN (" + ", ".join(f"'{status.value}'" for status in cls) + ")"
