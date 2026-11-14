import logging
import re
from typing import Any

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import iso_moment
from text_to_bi.superset_semantic_layer.core.exceptions import DatasetAccessError
from text_to_bi.superset_semantic_layer.core.security import is_superset_access_error

from ..dependencies import column_dictionary_repository, dataset_grain_repository
from ..exceptions import DataDictionaryValidationError
from ..models import ColumnDictionary, DatasetDictionary

logger = logging.getLogger(__name__)

# From finest to coarsest; `instant` rows are taken at irregular moments.
GRAINS = ("instant", "hour", "day", "week", "month", "quarter", "year")
TEMPORAL_KINDS = ("date", "timestamp")
MAX_ROW_KINDS = 20
MAX_LABEL_LENGTH = 255
MAX_ROW_KIND_VALUE_LENGTH = 255
SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIMESTAMP_TYPE = re.compile(r"TIMESTAMP|DATETIME", re.IGNORECASE)
_DATE_TYPE = re.compile(r"^\s*DATE\s*$", re.IGNORECASE)


# -------------------------TEMPORAL KIND------------------
def default_temporal_kind(data_type: Any, is_dttm: bool) -> str | None:
    """`timestamp` hoặc `date` đọc từ kiểu cột; cột Superset đánh dấu thời gian mà không rõ kiểu thì là timestamp."""
    text = str(data_type or "")
    if _TIMESTAMP_TYPE.search(text):
        return "timestamp"
    if _DATE_TYPE.match(text):
        return "date"
    return "timestamp" if is_dttm else None


def checked_temporal_kind(value: Any, index: int) -> str | None:
    if value is not None and value not in TEMPORAL_KINDS:
        raise DataDictionaryValidationError(f"columns[{index}].temporal_kind must be 'date', 'timestamp' or null.")
    return value


# -------------------------TIME SEMANTICS-----------------
def checked_time_semantics(time_column: Any, row_kind_column: Any, grains: Any, temporal_kinds: dict[str, str | None]) -> list[dict[str, Any]]:
    """Các grain sẽ lưu, kiểm tra với cột của dataset như sau khi lưu.

    `temporal_kinds` ánh xạ mọi cột của dataset sang loại thời gian của nó sau khi lưu.
    """
    if time_column is not None:
        if not isinstance(time_column, str) or time_column not in temporal_kinds:
            raise DataDictionaryValidationError("dataset.time_column must be a column of this dataset or null.")
        if temporal_kinds[time_column] is None:
            raise DataDictionaryValidationError("dataset.time_column must be a date or timestamp column.")
    if row_kind_column is not None:
        if not isinstance(row_kind_column, str) or row_kind_column not in temporal_kinds:
            raise DataDictionaryValidationError("dataset.row_kind_column must be a column of this dataset or null.")
        if row_kind_column == time_column:
            raise DataDictionaryValidationError("dataset.row_kind_column must differ from dataset.time_column.")
        if time_column is None:
            raise DataDictionaryValidationError("dataset.row_kind_column needs a dataset.time_column.")
    if not isinstance(grains, list):
        raise DataDictionaryValidationError("dataset.grains must be an array.")
    if grains and time_column is None:
        raise DataDictionaryValidationError("dataset.grains need a dataset.time_column.")
    if len(grains) > MAX_ROW_KINDS:
        raise DataDictionaryValidationError(f"dataset.grains may have at most {MAX_ROW_KINDS} kinds of rows.")
    if row_kind_column is None and len(grains) > 1:
        raise DataDictionaryValidationError("Several grains need a dataset.row_kind_column that tells the rows apart.")

    checked = []
    seen_values = set()
    for index, item in enumerate(grains):
        if not isinstance(item, dict) or set(item) - {"row_kind_value", "label", "grain"}:
            raise DataDictionaryValidationError(f"dataset.grains[{index}] must hold only row_kind_value, label and grain.")
        value = item.get("row_kind_value")
        if row_kind_column is None:
            if value is not None:
                raise DataDictionaryValidationError(f"dataset.grains[{index}].row_kind_value needs a dataset.row_kind_column.")
        elif not isinstance(value, str) or not value.strip() or len(value) > MAX_ROW_KIND_VALUE_LENGTH:
            raise DataDictionaryValidationError(f"dataset.grains[{index}].row_kind_value must be a value of {row_kind_column}.")
        if value in seen_values:
            raise DataDictionaryValidationError(f"dataset.grains has the kind of row {value} twice.")
        seen_values.add(value)
        label = item.get("label")
        if label is not None and (not isinstance(label, str) or len(label) > MAX_LABEL_LENGTH):
            raise DataDictionaryValidationError(f"dataset.grains[{index}].label must be a string of at most {MAX_LABEL_LENGTH} characters.")
        if item.get("grain") not in GRAINS:
            raise DataDictionaryValidationError(f"dataset.grains[{index}].grain must be one of {', '.join(GRAINS)}.")
        checked.append({"row_kind_value": value, "label": (label or "").strip() or value, "grain": item["grain"]})
    return checked


def save_time_semantics(record: DatasetDictionary, time_updates: dict[str, Any], rows_by_name: dict[str, ColumnDictionary]) -> None:
    """Lưu cột thời gian, cột loại dòng và các grain, kiểm tra với cột vừa cập nhật.

    Trường không gửi giữ giá trị đã lưu; các grain được thay cả bộ.
    """
    grain_repository = dataset_grain_repository()
    stored = grain_repository.read_by_dataset(record.id)
    time_column = time_updates.get("time_column", record.time_column)
    row_kind_column = time_updates.get("row_kind_column", record.row_kind_column)
    grains = time_updates.get("grains")
    if grains is None:
        grains = [{"row_kind_value": item.row_kind_value, "label": item.label, "grain": item.grain} for item in stored]
    temporal_kinds = {name: row.temporal_kind for name, row in rows_by_name.items()}
    checked = checked_time_semantics(time_column, row_kind_column, grains, temporal_kinds)
    record.time_column = time_column
    record.row_kind_column = row_kind_column
    grain_repository.update_dataset_grains(stored, record.id, checked)


# -------------------------GRAIN PROFILE------------------
def read_grain_profile(dataset: Any, time_column: str | None, row_kind_column: str | None, temporal_kind: str | None) -> dict[str, Any] | None:
    """Giá trị cột thời gian rơi thế nào ở mỗi loại dòng, kèm grain gợi ý; None khi truy vấn lỗi.

    Chạy một truy vấn ChartData tổng hợp với quyền người gọi, nên quyền và row-level security của Superset vẫn áp dụng.
    `temporal_kind` là loại đang hiện trên form; None thì đọc từ từ điển hoặc kiểu cột.
    """
    if temporal_kind is not None and temporal_kind not in TEMPORAL_KINDS:
        raise DataDictionaryValidationError("temporal_kind phải là date hoặc timestamp.")
    columns = {str(column.column_name): column for column in dataset.columns}
    if time_column not in columns or getattr(columns[time_column], "expression", None):
        raise DataDictionaryValidationError("time_column must be a physical column of this dataset.")
    if row_kind_column is not None and (row_kind_column not in columns or getattr(columns[row_kind_column], "expression", None)):
        raise DataDictionaryValidationError("row_kind_column must be a physical column of this dataset.")
    # The kind the administrator sees in the form, which a page not saved yet may still show as its default.
    entry = column_dictionary_repository().read_by_column_name(dataset.id, time_column)
    temporal_kind = temporal_kind or (entry.temporal_kind if entry else None)
    if temporal_kind is None:
        column = columns[time_column]
        temporal_kind = default_temporal_kind(getattr(column, "type", None), bool(getattr(column, "is_dttm", False)))
    if temporal_kind not in TEMPORAL_KINDS:
        raise DataDictionaryValidationError("time_column must be a date or timestamp column.")
    payload = build_grain_profile_payload(dataset, time_column, row_kind_column, temporal_kind)
    from superset.charts.schemas import ChartDataQueryContextSchema
    from superset.commands.chart.data.get_data_command import ChartDataCommand

    try:
        command = ChartDataCommand(ChartDataQueryContextSchema().load(payload))
        command.validate()
        result = command.run()["queries"][0]
    except Exception as ex:
        if is_superset_access_error(ex):
            raise DatasetAccessError() from ex
        logger.exception("Reading the grain profile of %s failed", dataset.table_name)
        return None
    if result.get("error"):
        logger.error("Grain profile query of %s failed: %s", dataset.table_name, result["error"])
        return None
    profiles, too_many = grain_profile_from_rows(result.get("data", []), row_kind_column)
    return {"time_column": time_column, "row_kind_column": row_kind_column, "profiles": profiles, "too_many_kinds": too_many}


def build_grain_profile_payload(dataset: Any, time_column: str, row_kind_column: str | None, temporal_kind: str) -> dict[str, Any]:
    """Một dòng tổng hợp cho mỗi loại dòng: số dòng, thời điểm đầu và cuối, số giá trị lệch giờ chẵn, nửa đêm, ngày đầu tháng.

    Chỉ dùng EXTRACT, CAST sang DATE và COUNT DISTINCT để chạy được trên các SQL engine thường gặp. Cột date không có
    giờ trong ngày (PostgreSQL từ chối EXTRACT(HOUR) trên date) nên không đếm lệch giờ hay nửa đêm. Tên cột được kiểm
    tra là định danh đơn giản trước khi vào SQL.
    """
    for name in (time_column, row_kind_column):
        if name is not None and not SIMPLE_IDENTIFIER.match(name):
            raise DataDictionaryValidationError("Grain detection needs plainly named columns.")
    hour, minute, second = (f"EXTRACT({part} FROM {time_column})" for part in ("HOUR", "MINUTE", "SECOND"))
    day = f"EXTRACT(DAY FROM {time_column})"

    def counted(condition: str, label: str) -> dict[str, Any]:
        return {"expressionType": "SQL", "sqlExpression": f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)", "label": label}

    metrics = [
        {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "row_count"},
        {"expressionType": "SQL", "sqlExpression": f"MIN({time_column})", "label": "first_moment"},
        {"expressionType": "SQL", "sqlExpression": f"MAX({time_column})", "label": "last_moment"},
        {"expressionType": "SQL", "sqlExpression": f"COUNT(DISTINCT {time_column})", "label": "moments"},
        {"expressionType": "SQL", "sqlExpression": f"COUNT(DISTINCT CAST({time_column} AS DATE))", "label": "days"},
        counted(f"{day} <> 1", "off_first_day"),
    ]
    if temporal_kind == "timestamp":
        metrics += [
            counted(f"{minute} <> 0 OR {second} <> 0", "off_the_hour"),
            counted(f"{hour} <> 0 OR {minute} <> 0 OR {second} <> 0", "off_midnight"),
        ]
    return {
        "datasource": {"id": dataset.id, "type": "table"},
        "queries": [{"columns": [row_kind_column] if row_kind_column else [], "metrics": metrics, "row_limit": MAX_ROW_KINDS + 1}],
        "result_type": "full",
        "result_format": "json",
    }


def suggested_grain(profile: dict[str, Any]) -> str | None:
    """Grain khớp với giá trị: thời điểm bất kỳ, giờ chẵn, nửa đêm hay ngày đầu tháng."""
    if profile["row_count"] == 0:
        return None
    if profile["off_the_hour"]:
        return "instant"
    if profile["off_midnight"]:
        return "hour"
    if not profile["off_first_day"] and profile["moments"] > 1:
        return "month"
    return "day"


def grain_profile_from_rows(rows: list[dict[str, Any]], row_kind_column: str | None) -> tuple[list[dict[str, Any]], bool]:
    """Hồ sơ của mỗi loại dòng, sắp theo giá trị, và cột có nhiều loại hơn danh sách grain giữ được hay không.

    Loại dòng không ghi thời gian bị bỏ qua.
    """
    profiles = []
    for row in rows[:MAX_ROW_KINDS]:
        value = row.get(row_kind_column) if row_kind_column else None
        if row_kind_column and value in (None, ""):
            continue
        profile = {
            "row_kind_value": None if value is None else str(value),
            "row_count": _count(row.get("row_count")),
            "first_moment": iso_moment(row.get("first_moment")),
            "last_moment": iso_moment(row.get("last_moment")),
            "moments": _count(row.get("moments")),
            "days": _count(row.get("days")),
            "off_the_hour": _count(row.get("off_the_hour")),
            "off_midnight": _count(row.get("off_midnight")),
            "off_first_day": _count(row.get("off_first_day")),
        }
        profile["suggested_grain"] = suggested_grain(profile)
        profiles.append(profile)
    profiles.sort(key=lambda profile: profile["row_kind_value"] or "")
    return profiles, len(rows) > MAX_ROW_KINDS


def _count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
