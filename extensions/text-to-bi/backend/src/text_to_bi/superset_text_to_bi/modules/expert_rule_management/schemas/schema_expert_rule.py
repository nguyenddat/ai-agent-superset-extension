import math
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

Operator = Literal[
    "equals", "not_equals", "contains", "not_contains", "greater_than", "greater_than_or_equal",
    "less_than", "less_than_or_equal", "in", "not_in", "is_null", "is_not_null",
]
ValueType = Literal["string", "number", "boolean", "null", "array"]


class RuleCondition(BaseModel):
    column_name: str = Field(min_length=1, max_length=255)
    operator: Operator
    value_type: ValueType
    value: Any = None

    @model_validator(mode="after")
    def validate_value(self) -> "RuleCondition":
        value = self.value
        valid = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value)),
            "boolean": isinstance(value, bool),
            "null": value is None,
            "array": isinstance(value, list) and bool(value)
            and all(isinstance(item, (str, int, float, bool))
                    and (not isinstance(item, float) or math.isfinite(item)) for item in value),
        }
        if not valid[self.value_type]:
            raise ValueError("Giá trị điều kiện không khớp kiểu đã chọn.")
        if self.operator in ("is_null", "is_not_null") and self.value_type != "null":
            raise ValueError("Điều kiện null cần giá trị null.")
        if self.operator in ("in", "not_in") and self.value_type != "array":
            raise ValueError("Điều kiện tập hợp cần giá trị dạng mảng.")
        if self.value_type == "array" and self.operator not in ("in", "not_in"):
            raise ValueError("Giá trị mảng chỉ dùng với điều kiện tập hợp.")
        if self.operator in ("contains", "not_contains") and self.value_type != "string":
            raise ValueError("Điều kiện chứa cần chuỗi.")
        if self.operator in ("greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal") \
                and self.value_type != "number":
            raise ValueError("Điều kiện so sánh độ lớn cần số.")
        return self


class RuleException(BaseModel):
    when: str = Field(min_length=1, max_length=2000)
    outcome: str = Field(min_length=1, max_length=2000)


class RuleExample(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    intent: str = Field(min_length=1, max_length=2000)


class MetricRef(BaseModel):
    kind: Literal["metric", "superset_metric"]
    target_key: str = Field(min_length=1, max_length=40)


class RuleContent(BaseModel):
    description: str | None = Field(default=None, max_length=10000)
    conditions: list[RuleCondition] = Field(min_length=1, max_length=50)
    exceptions: list[RuleException] = Field(default_factory=list, max_length=50)
    examples: list[RuleExample] = Field(default_factory=list, max_length=50)
    glossary_term_ids: list[UUID] = Field(min_length=1, max_length=50)
    metric_refs: list[MetricRef] = Field(default_factory=list, max_length=50)


class RuleCreate(RuleContent):
    dataset_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    business_domain_ids: list[UUID] = Field(default_factory=list, max_length=50)


class RuleUpdate(RuleContent):
    expected_revision: int = Field(ge=1)
    business_domain_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ReviewIn(BaseModel):
    expected_revision: int = Field(ge=1)
