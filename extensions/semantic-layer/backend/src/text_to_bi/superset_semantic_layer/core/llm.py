from functools import lru_cache

from langchain_openai import ChatOpenAI

from .config import settings

# The contradiction judge runs inside a request: a stalled provider must not hold it past Gunicorn's 120-second
# worker timeout, so one try and one retry fit. AutoFill keeps the client defaults.
JUDGEMENT_TIMEOUT_SECONDS = 45
JUDGEMENT_MAX_RETRIES = 1


def _build_chat_model(**limits) -> ChatOpenAI:
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY chưa được cấu hình. Đặt biến này trong file .env ở thư mục gốc repo "
            "rồi khởi động lại dịch vụ superset."
        )
    return ChatOpenAI(
        model=settings.OPENROUTER_MODEL,
        temperature=0.0,
        max_tokens=4096,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        **limits,
    )


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    """Model chat của AI AutoFill, giữ thời hạn mặc định của client."""
    return _build_chat_model()


@lru_cache(maxsize=1)
def get_judgement_chat_model() -> ChatOpenAI:
    """Model chat chấm mâu thuẫn, có giới hạn thời gian để request không vượt timeout của Gunicorn."""
    return _build_chat_model(timeout=JUDGEMENT_TIMEOUT_SECONDS, max_retries=JUDGEMENT_MAX_RETRIES)
