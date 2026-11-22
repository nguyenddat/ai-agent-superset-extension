from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GlossaryLinkIn(BaseModel):
    kind: Literal["table", "column", "metric", "superset_metric"]
    target_key: str = Field(min_length=1, max_length=300)


class GlossaryContent(BaseModel):
    definition: str = Field(min_length=1, max_length=10000)
    synonyms: list[str] = Field(default_factory=list, max_length=50)
    links: list[GlossaryLinkIn] = Field(default_factory=list, max_length=100)


class GlossaryCreate(GlossaryContent):
    dataset_id: int = Field(gt=0)
    canonical_name: str = Field(min_length=1, max_length=255)
    business_domain_ids: list[UUID] = Field(default_factory=list, max_length=50)


class GlossaryUpdate(GlossaryContent):
    expected_revision: int = Field(ge=1)
    business_domain_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ReviewIn(BaseModel):
    expected_revision: int = Field(ge=1)
