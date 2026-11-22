from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DefinitionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    concept: str | None = Field(default=None, max_length=200)
    definition: str = Field(min_length=1, max_length=2000)


class ReviewUpdate(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)
    status: Literal["pending", "promoted", "ignored"]
