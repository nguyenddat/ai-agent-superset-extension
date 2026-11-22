from typing import Literal

from pydantic import BaseModel, Field


class ColumnDependencyIn(BaseModel):
    source_dataset_id: int = Field(gt=0)
    source_column_name: str = Field(min_length=1, max_length=255)
    target_column_name: str | None = Field(default=None, max_length=255)
    role: Literal["value", "group", "join", "filter"]


class TransformationIn(BaseModel):
    target_dataset_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    sql_text: str | None = None
    origin: Literal["manual", "sql_job", "view_sql"] = "manual"
    source_dataset_ids: list[int] = Field(min_length=1, max_length=500)
    dependencies: list[ColumnDependencyIn] = Field(default_factory=list, max_length=5000)


class PreviewIn(BaseModel):
    target_dataset_id: int = Field(gt=0)
    sql_text: str = Field(min_length=1)
