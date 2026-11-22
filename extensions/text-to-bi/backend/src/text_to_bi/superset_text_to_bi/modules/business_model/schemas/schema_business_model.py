from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LayerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, max_length=16)
    level: int = Field(default=0, ge=0)
    sort_order: int = Field(default=0, ge=0)

class LayerOut(LayerIn):
    model_config = ConfigDict(from_attributes=True)
    id: Any

class DomainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, max_length=16)
    dataset_ids: list[int] = Field(default_factory=list, max_length=1000)

class CanvasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layout: dict[str, Any]


class LayerOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    levels: list[list[str]] = Field(max_length=100)

class DomainOut(BaseModel):
    id: str
    name: str
    description: str | None
    color: str | None
    dataset_ids: list[int]

class DatasetLayerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer_id: str | None
