from enum import Enum


class ContractOrigin(str, Enum):
    """Ai tạo bản nháp: quản trị viên, hoặc AI Agent (bản nháp của AI Agent trả số tạm cho người hỏi)."""

    MANUAL = "manual"
    AI_AGENT = "ai_agent"
