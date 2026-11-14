import json
import logging
from collections.abc import Generator, Iterator
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from superset import db
from superset.connectors.sqla.models import SqlaTable

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import sse_event
from text_to_bi.superset_semantic_layer.core.llm import get_chat_model

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository
from ..exceptions import AutoFillUnavailableError, NoColumnsToDescribeError, SuggestionInProgressError
from ..prompts.prompt_column_dictionary import system_prompt
from ..prompts.prompt_dataset_dictionary import dataset_system_prompt
from .srv_autofill_lock import AutoFillLease, claim_autofill
from .srv_seeding import seed_dictionary

logger = logging.getLogger(__name__)

class ColumnDictionarySuggestion(BaseModel):
    column_name: str = Field(description="Tên cột vật lý, giữ nguyên như đầu vào.")
    display_name: str = Field(description="Nhãn dễ hiểu bằng tiếng Việt, tối đa 255 ký tự.")
    unit: str | None = Field(default=None, description="Đơn vị đo nếu biết chắc, nếu không thì null.")
    business_term: str | None = Field(default=None, description="Mô tả nghiệp vụ ngắn nếu đủ căn cứ, nếu không thì null.")


class ColumnDictionarySuggestions(BaseModel):
    suggestions: list[ColumnDictionarySuggestion] = Field(description="Đề xuất cho toàn bộ cột được gửi vào, mỗi tên cột xuất hiện đúng một lần.")


class DatasetDictionarySuggestion(BaseModel):
    display_name: str = Field(description="Tên hiển thị ngắn gọn, dễ hiểu bằng tiếng Việt.")
    description: str | None = Field(default=None, description="Mô tả dataset, null nếu thiếu căn cứ.")
    grain: str | None = Field(default=None, description="Mức độ chi tiết của một bản ghi, null nếu chưa rõ.")
    create_column: str | None = Field(
        default=None, description="Tên cột phù hợp nhất để xác định thời điểm/tạo bản ghi, phải khớp tên cột đầu vào hoặc null."
    )


# -------------------------STREAM-------------------------
def start_autofill(dataset: SqlaTable) -> "AutoFillStream":
    """Kiểm tra AutoFill chạy được cho dataset rồi trả luồng sự kiện SSE gợi ý và lưu metadata từ điển.

    Các kiểm tra (cột, API key, lượt gợi ý đang chạy) ném lỗi ngay, trước khi luồng bắt đầu.
    """
    if not dataset.columns:
        raise NoColumnsToDescribeError()
    try:
        get_chat_model()
    except RuntimeError as ex:
        # A missing API key would otherwise surface only as a generic error in the middle of the stream.
        logger.error("AI AutoFill unavailable: %s", ex)
        raise AutoFillUnavailableError(str(ex)) from ex
    agent_context = _agent_context(dataset)
    # The seed commits, so each LLM call below runs with no transaction open; a batch reads and writes its
    # rows only after the model has answered.
    lease = claim_autofill(db.engine, dataset.id)
    if lease is None:
        raise SuggestionInProgressError()
    try:
        seed_dictionary(dataset)
        return AutoFillStream(_autofill_events(dataset.id, dataset.table_name, agent_context, lease), lease)
    except BaseException:
        lease.close()
        raise


def _autofill_events(dataset_id: int, table_name: str, agent_context: dict[str, Any], lease: AutoFillLease) -> Generator[str, None, None]:
    """Gợi ý từng lô cột, lưu vào chỗ còn trống và commit mỗi lô, rồi gợi ý metadata của dataset."""
    column_repository = column_dictionary_repository()
    dataset_repository = dataset_dictionary_repository()
    total = len(agent_context["columns"])
    try:
        yield sse_event("status", {"total": total, "processed": 0, "message": "Đang chuẩn bị gợi ý"})
        processed = 0
        for suggestions in suggest_column_dictionary_batches(agent_context):
            rows_by_name = {row.column_name: row for row in column_repository.read_by_dataset(dataset_id)}
            saved_suggestions = []
            for item in suggestions:
                row = rows_by_name.get(item["column_name"])
                if row is None:
                    continue
                values = {}
                if not row.display_name.strip() or row.display_name.strip() == row.column_name:
                    values["display_name"] = str(item["display_name"] or row.column_name)[:255]
                if not (row.unit or "").strip():
                    values["unit"] = str(item["unit"] or "")[:128] or None
                if not (row.business_term or "").strip():
                    values["business_term"] = item["business_term"] or None
                if values:
                    column_repository.update(row, values)
                saved_suggestions.append(
                    {"column_name": row.column_name, "display_name": row.display_name, "unit": row.unit, "business_term": row.business_term}
                )
            db.session.commit()
            processed += len(suggestions)
            yield sse_event("suggestions", {"suggestions": saved_suggestions, "processed": processed, "total": total})
            yield sse_event("status", {"total": total, "processed": processed, "message": f"Đã xử lý {processed}/{total} cột"})
        dataset_suggestion = suggest_dataset_dictionary(agent_context)
        dataset_record = dataset_repository.read(dataset_id)
        dataset_values = {}
        if not (dataset_record.display_name or "").strip() or dataset_record.display_name.strip() == table_name:
            dataset_values["display_name"] = dataset_suggestion["display_name"]
        if not (dataset_record.description or "").strip() and dataset_suggestion["description"]:
            dataset_values["description"] = dataset_suggestion["description"]
        if not (dataset_record.grain or "").strip() and dataset_suggestion["grain"]:
            dataset_values["grain"] = dataset_suggestion["grain"]
        if not dataset_record.create_column and dataset_suggestion["create_column"]:
            dataset_values["create_column"] = dataset_suggestion["create_column"]
        if dataset_values:
            dataset_repository.update(dataset_record, dataset_values)
        db.session.commit()
        dataset_fields = {
            "display_name": dataset_record.display_name,
            "description": dataset_record.description,
            "grain": dataset_record.grain,
            "create_column": dataset_record.create_column,
        }
        yield sse_event("dataset_suggestion", {"dataset": dataset_fields})
        yield sse_event("done", {"processed": processed, "total": total})
    except Exception as ex:
        db.session.rollback()
        logger.exception("Column dictionary agent failed (dataset_id=%s)", dataset_id)
        # Batches saved before the failure are already committed and shown; only the rest is missing.
        yield sse_event("error", {"message": _failure_message(getattr(ex, "status_code", None))})
    finally:
        lease.close()


def _agent_context(dataset: SqlaTable) -> dict[str, Any]:
    return {
        "dataset_name": dataset.table_name,
        "dataset_description": dataset.description,
        "columns": [
            {
                "column_name": str(column.column_name),
                "data_type": str(getattr(column, "type", None) or "UNKNOWN")[:128],
                "superset_display_name": getattr(column, "verbose_name", None),
                "description": getattr(column, "description", None),
                "is_datetime": bool(getattr(column, "is_dttm", False)),
            }
            for column in dataset.columns
        ],
    }


def _failure_message(status_code: Any) -> str:
    if status_code == 402:
        return "OpenRouter từ chối yêu cầu vì hết hạn mức credit của API key. Nạp thêm credit hoặc thử lại sau."
    if status_code == 401:
        return "OpenRouter từ chối API key. Kiểm tra OPENROUTER_API_KEY trong file .env ở thư mục gốc repo."
    return "Không thể tạo gợi ý từ điển cột."


class AutoFillStream:
    def __init__(self, events: Generator[str, None, None], lease: AutoFillLease) -> None:
        self.events, self.lease = events, lease

    def __iter__(self):
        return self

    def __next__(self) -> str:
        return next(self.events)

    def close(self) -> None:
        try:
            self.events.close()
        finally:
            self.lease.close()


# -------------------------AGENT--------------------------
def suggest_dataset_dictionary(dataset: dict[str, Any]) -> dict[str, Any]:
    """Gợi ý metadata mô tả của dataset và cột ghi nhận thời điểm (nếu có)."""
    result = _dataset_agent().invoke({"messages": [HumanMessage(content=json.dumps(dataset, ensure_ascii=False, indent=2))]})
    raw = result.get("structured_response") if isinstance(result, dict) else None
    if raw is None:
        raise RuntimeError("Agent không trả về structured response cho dataset.")
    suggestion = raw if isinstance(raw, DatasetDictionarySuggestion) else DatasetDictionarySuggestion.model_validate(raw)
    suggestion.display_name = suggestion.display_name.strip()
    if not suggestion.display_name or len(suggestion.display_name) > 255:
        raise ValueError("Agent trả display_name dataset không hợp lệ.")
    if suggestion.description is not None:
        suggestion.description = suggestion.description.strip()[:4000] or None
    if suggestion.grain is not None:
        suggestion.grain = suggestion.grain.strip()[:2000] or None
    if suggestion.create_column is not None:
        suggestion.create_column = suggestion.create_column.strip() or None
        valid_columns = {str(column["column_name"]) for column in dataset.get("columns", [])}
        if suggestion.create_column not in valid_columns:
            raise ValueError("Agent trả create_column không thuộc dataset.")
    return suggestion.model_dump(mode="json")


def suggest_column_dictionary_batches(dataset: dict[str, Any], batch_size: int = 4) -> Iterator[list[dict[str, Any]]]:
    """Gợi ý theo từng lô nhỏ độc lập để stream dần."""
    columns = dataset.get("columns")
    if not isinstance(columns, list):
        raise ValueError("Dataset context must contain a columns list.")  # noqa: TRY004
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    for start in range(0, len(columns), batch_size):
        yield _suggest_column_batch({**dataset, "columns": columns[start : start + batch_size]})


def suggest_column_dictionary(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """Gợi ý tên hiển thị, đơn vị và thuật ngữ nghiệp vụ cho mọi cột của dataset."""
    return [suggestion for batch in suggest_column_dictionary_batches(dataset) for suggestion in batch]


def _suggest_column_batch(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """Gợi ý tên hiển thị, đơn vị và thuật ngữ nghiệp vụ cho một lô cột."""
    result = _column_agent().invoke({"messages": [HumanMessage(content=json.dumps(dataset, ensure_ascii=False, indent=2))]})
    raw = result.get("structured_response") if isinstance(result, dict) else None
    if raw is None:
        raise RuntimeError("Agent không trả về structured response.")
    response = raw if isinstance(raw, ColumnDictionarySuggestions) else ColumnDictionarySuggestions.model_validate(raw)
    expected_names = [item["column_name"] for item in dataset["columns"]]
    suggestions = response.suggestions
    suggested_names = [suggestion.column_name for suggestion in suggestions]
    if len(suggested_names) != len(set(suggested_names)) or set(suggested_names) != set(expected_names):
        raise ValueError("Agent trả về thiếu, trùng hoặc dư column_name.")
    for suggestion in suggestions:
        suggestion.display_name = suggestion.display_name.strip()
        if not suggestion.display_name or len(suggestion.display_name) > 255:
            raise ValueError(f"Agent trả display_name không hợp lệ cho {suggestion.column_name}.")
        if suggestion.unit is not None:
            suggestion.unit = suggestion.unit.strip()[:128] or None
        if suggestion.business_term is not None:
            suggestion.business_term = suggestion.business_term.strip()[:2000] or None
    return [suggestion.model_dump(mode="json") for suggestion in suggestions]


@lru_cache(maxsize=1)
def _column_agent():
    return create_agent(
        model=get_chat_model(), name="column-dictionary-agent", tools=[], response_format=ColumnDictionarySuggestions, system_prompt=system_prompt
    )


@lru_cache(maxsize=1)
def _dataset_agent():
    return create_agent(
        model=get_chat_model(), name="dataset-dictionary-agent", tools=[], response_format=DatasetDictionarySuggestion, system_prompt=dataset_system_prompt
    )
