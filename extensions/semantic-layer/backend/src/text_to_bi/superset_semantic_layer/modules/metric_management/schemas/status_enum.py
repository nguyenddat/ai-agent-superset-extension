from enum import Enum


class ContractOrigin(str, Enum):
    MANUAL = "manual"
    AI_AGENT = "ai_agent"
