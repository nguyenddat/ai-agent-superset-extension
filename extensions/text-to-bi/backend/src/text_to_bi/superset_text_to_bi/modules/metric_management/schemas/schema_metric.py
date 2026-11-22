from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class MetricCreate(BaseModel):
    dataset_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    expression: str = Field(min_length=1, max_length=10000)
    label: str | None = Field(default=None, max_length=255)
    description: str | None = None
    format: str | None = Field(default=None, max_length=128)
    currency: str | None = Field(default=None, max_length=16)
    metric_type: str | None = Field(default=None, max_length=64)
    warning_text: str | None = None
    business_domain_ids: list[UUID] = Field(default_factory=list, max_length=50)


class MetricPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    expression: str | None = Field(default=None, min_length=1, max_length=10000)
    label: str | None = Field(default=None, max_length=255)
    description: str | None = None
    format: str | None = Field(default=None, max_length=128)
    currency: str | None = Field(default=None, max_length=16)
    metric_type: str | None = Field(default=None, max_length=64)
    warning_text: str | None = None
    is_active: bool | None = None
    business_domain_ids: list[UUID] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def require_non_nullable_values(self) -> MetricPatch:
        for field in ("name", "expression", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self
