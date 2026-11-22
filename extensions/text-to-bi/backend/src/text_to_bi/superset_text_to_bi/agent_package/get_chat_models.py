import json
from functools import lru_cache
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from text_to_bi.superset_text_to_bi.core.config import settings

Output = TypeVar("Output", bound=BaseModel)


# Raises RuntimeError while OPENROUTER_API_KEY is unset; lru_cache keeps no failed result, so setting the key and
# restarting Superset is enough.
@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.OPENROUTER_MODEL,
        temperature=0.0,
        max_tokens=4096,
        timeout=60,
        max_retries=2,
        api_key=settings.require_openrouter_api_key(),
        base_url=settings.OPENROUTER_BASE_URL,
    )


def structured_model(schema: type[Output]) -> Any:
    return get_chat_model().with_structured_output(schema, method="function_calling")


def build_messages(prompt: str, context: dict[str, Any]) -> list[SystemMessage | HumanMessage]:
    return [SystemMessage(content=prompt), HumanMessage(content=json.dumps(context, ensure_ascii=False, indent=2))]
