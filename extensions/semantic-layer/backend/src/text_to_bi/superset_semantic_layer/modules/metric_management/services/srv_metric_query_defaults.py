import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import iso_moment
from text_to_bi.superset_semantic_layer.modules.data_dictionary.dependencies import (
    column_dictionary_repository,
    dataset_dictionary_repository,
    dataset_grain_repository,
)
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_grain import GRAINS

from ..dependencies import metric_definition_repository
from ..exceptions import MetricContractValidationError

QUERY_DEFAULT_FIELDS = ("grain", "row_kind_value", "time_column", "time_window", "time_anchor", "default_filters")
# A metric is read by the hour or coarser: `instant` rows have no regular step to group them by.
READ_GRAINS = GRAINS[1:]
TIME_ANCHORS = ("now", "latest_data")
# The period Superset groups a temporal column by for each grain (ChartData `timeGrain`); weeks start on Monday.
TIME_GRAIN_DURATIONS = {"hour": "PT1H", "day": "P1D", "week": "P1W", "month": "P1M", "quarter": "P3M", "year": "P1Y"}
# The warehouse stores Vietnam's wall-clock time (Asia/Bangkok, UTC+7) without a zone.
DATA_TIMEZONE = timezone(timedelta(hours=7))
TIME_WINDOW = re.compile(
    r"^(?:last_(?P<count>[1-9][0-9]{0,2})_(?P<last_unit>hour|day|week|month|quarter|year)"
    r"|(?P<mode>current|previous)_(?P<unit>day|week|month|quarter|year)"
    r"|(?P<to_date_unit>day|week|month|quarter|year)_to_date)$"
)
MAX_DEFAULT_FILTERS = 10
FILTER_OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN")
MAX_FILTER_VALUES = 100
MAX_FILTER_STRING_LENGTH = 1024
TEMPORAL_TYPE = re.compile(r"DATE|TIME", re.IGNORECASE)
NUMERIC_TYPE = re.compile(r"INT|FLOAT|DOUBLE|NUMERIC|DECIMAL|REAL|SERIAL|NUMBER", re.IGNORECASE)
MOMENT_TEXT = re.compile(
    r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)


@dataclass(frozen=True)
class MetricQueryDefaults:
    """Cách đọc metric khi câu hỏi không nói khác: grain, loại dòng, mốc thời gian và bộ lọc mặc định.

    `row_kind_column` và `native_grain` lấy từ từ điển dữ liệu của dataset, không lưu cùng metric.
    """

    grain: str | None = None
    row_kind_value: str | None = None
    time_column: str | None = None
    time_window: str | None = None
    time_anchor: str | None = None
    default_filters: tuple[dict[str, Any], ...] = ()
    row_kind_column: str | None = None
    native_grain: str | None = None

    def is_empty(self) -> bool:
        return not any((self.grain, self.row_kind_value, self.time_column, self.time_window, self.default_filters))

    def as_dict(self) -> dict[str, Any]:
        return {
            "grain": self.grain,
            "row_kind_column": self.row_kind_column,
            "row_kind_value": self.row_kind_value,
            "native_grain": self.native_grain,
            "time_column": self.time_column,
            "time_window": self.time_window,
            "time_anchor": self.time_anchor,
            "default_filters": [dict(item) for item in self.default_filters],
        }

    def stored_values(self) -> dict[str, Any]:
        """Giá trị lưu vào các cột mặc định của MetricDefinition."""
        filters = json.dumps(list(self.default_filters), ensure_ascii=False) if self.default_filters else None
        return {
            "grain": self.grain,
            "row_kind_value": self.row_kind_value,
            "time_column": self.time_column,
            "time_window": self.time_window,
            "time_anchor": self.time_anchor,
            "default_filters": filters,
        }


@dataclass(frozen=True)
class DatasetTimeContext:
    """Những gì từ điển dữ liệu nói về thời gian của một dataset."""

    time_column: str | None
    row_kind_column: str | None
    grains: dict[str | None, str]
    temporal_columns: set[str]
    row_kind_labels: dict[str | None, str | None] = field(default_factory=dict)


# -------------------------READ---------------------------
def dataset_time_context(dataset: Any) -> DatasetTimeContext:
    """Cột thời gian chính, cột loại dòng kèm grain từng loại và các cột ngày/giờ lọc được của dataset."""
    return dataset_time_contexts([dataset])[dataset.id]


def dataset_time_contexts(datasets: list[Any]) -> dict[int, DatasetTimeContext]:
    """`dataset_time_context` của nhiều dataset, đọc từ điển dữ liệu một lần."""
    dataset_ids = [dataset.id for dataset in datasets]
    if not dataset_ids:
        return {}
    dictionaries = {item.id: item for item in dataset_dictionary_repository().read_by_ids(dataset_ids)}
    temporal_kinds = {
        (entry.dataset_id, entry.column_name): entry.temporal_kind
        for entry in column_dictionary_repository().read_by_datasets(dataset_ids)
    }
    grains: dict[int, dict[str | None, str]] = {}
    labels: dict[int, dict[str | None, str | None]] = {}
    for grain in dataset_grain_repository().read_by_datasets(dataset_ids):
        grains.setdefault(grain.dataset_id, {})[grain.row_kind_value] = grain.grain
        labels.setdefault(grain.dataset_id, {})[grain.row_kind_value] = grain.label
    contexts = {}
    for dataset in datasets:
        dictionary = dictionaries.get(dataset.id)
        contexts[dataset.id] = DatasetTimeContext(
            time_column=getattr(dictionary, "time_column", None),
            row_kind_column=getattr(dictionary, "row_kind_column", None),
            grains=grains.get(dataset.id, {}),
            temporal_columns={
                column.column_name
                for column in dataset.columns
                if column.is_active is True
                and not column.expression
                and column.filterable is True
                and (column.is_dttm or temporal_kinds.get((dataset.id, column.column_name)))
            },
            row_kind_labels=labels.get(dataset.id, {}),
        )
    return contexts


def dataset_column_labels(datasets: list[Any]) -> dict[int, dict[str, str]]:
    """Nhãn cột của từng dataset: tên hiển thị trong từ điển dữ liệu, không có thì tên của Superset."""
    labels = {
        dataset.id: {column.column_name: column.verbose_name for column in dataset.columns if column.verbose_name}
        for dataset in datasets
    }
    dataset_ids = list(labels)
    for column in column_dictionary_repository().read_by_datasets(dataset_ids) if dataset_ids else []:
        if column.display_name:
            labels[column.dataset_id][column.column_name] = column.display_name
    return labels


def query_defaults_on(dataset_ids: Iterable[int]) -> dict[tuple[int, int], MetricQueryDefaults]:
    """Giá trị mặc định của mọi metric đã đặt trong các dataset, theo (dataset ID, metric ID)."""
    dataset_ids = sorted(set(dataset_ids))
    definitions = metric_definition_repository().read_on_datasets(dataset_ids) if dataset_ids else []
    declared = [item for item in definitions if any(getattr(item, field) for field in QUERY_DEFAULT_FIELDS)]
    if not declared:
        return {}
    declared_ids = sorted({item.dataset_id for item in declared})
    dictionaries = dataset_dictionary_repository().read_by_ids(declared_ids)
    row_kind_columns = {item.id: item.row_kind_column for item in dictionaries}
    grains = _grains_on(declared_ids)
    loaded = {}
    for definition in declared:
        context = DatasetTimeContext(
            time_column=None,
            row_kind_column=row_kind_columns.get(definition.dataset_id),
            grains=grains.get(definition.dataset_id, {}),
            temporal_columns=set(),
        )
        if defaults := stored_query_defaults(definition, context):
            loaded[(definition.dataset_id, definition.metric_id)] = defaults
    return loaded


def query_defaults_for(dataset_id: int, metric_id: int) -> MetricQueryDefaults | None:
    """Giá trị mặc định của một metric; None nếu chưa đặt."""
    return query_defaults_on([dataset_id]).get((dataset_id, metric_id))


def stored_query_defaults(definition: Any, context: DatasetTimeContext) -> MetricQueryDefaults | None:
    """Giá trị mặc định đã lưu của metric, kèm thông tin loại dòng từ từ điển dữ liệu; None nếu chưa đặt."""
    if definition is None:
        return None
    try:
        filters = json.loads(definition.default_filters or "[]")
    except (TypeError, ValueError):
        filters = []
    defaults = MetricQueryDefaults(
        grain=definition.grain,
        row_kind_value=definition.row_kind_value,
        time_column=definition.time_column,
        time_window=definition.time_window,
        time_anchor=definition.time_anchor,
        default_filters=tuple(item for item in filters if isinstance(item, dict)),
    )
    if defaults.is_empty():
        return None
    return replace(
        defaults,
        row_kind_column=context.row_kind_column if defaults.row_kind_value else None,
        native_grain=native_grain(defaults.row_kind_value, context.grains),
    )


def native_grain(row_kind_value: str | None, grains: dict[str | None, str]) -> str | None:
    """Grain của các dòng metric đọc: của loại dòng đã chọn, hoặc grain duy nhất của dataset."""
    if row_kind_value is not None:
        return grains.get(row_kind_value)
    return next(iter(grains.values())) if len(grains) == 1 else None


# -------------------------CHECK--------------------------
def checked_query_defaults(
    body: Any, columns: dict[str, Any], context: DatasetTimeContext, formula_row_kinds: set[str]
) -> MetricQueryDefaults:
    """Kiểm tra giá trị mặc định quản trị viên gửi lên theo dataset và công thức; sai thì báo lỗi 400.

    `formula_row_kinds` là các loại dòng mà công thức đã chọn sẵn.
    """
    if not isinstance(body, dict) or set(body) - set(QUERY_DEFAULT_FIELDS):
        raise MetricContractValidationError(
            "Chỉ gửi grain, row_kind_value, time_column, time_window, time_anchor và default_filters."
        )
    grain = _optional_text(body, "grain")
    row_kind_value = _optional_text(body, "row_kind_value")
    time_column = _optional_text(body, "time_column")
    time_window = _optional_text(body, "time_window")
    time_anchor = _optional_text(body, "time_anchor")
    raw_filters = body.get("default_filters") or []
    if not isinstance(raw_filters, list):
        raise MetricContractValidationError("default_filters phải là một mảng.")
    declared = bool(grain or row_kind_value or time_column or time_window or raw_filters)
    grains, row_kind_column = context.grains, context.row_kind_column

    # Loại dòng
    if row_kind_value is not None:
        if row_kind_column is None:
            raise MetricContractValidationError(
                "Dataset chưa khai báo cột phân loại dòng trong từ điển dữ liệu nên metric không chọn được loại dòng."
            )
        if row_kind_value not in grains:
            raise MetricContractValidationError(
                f"Loại dòng “{row_kind_value}” chưa được khai báo grain trong từ điển dữ liệu của dataset."
            )
    selected_kinds = {kind for kind in formula_row_kinds if kind in grains}
    if row_kind_column is not None and len(selected_kinds) == 1:
        (selected,) = selected_kinds
        if row_kind_value is None and declared:
            row_kind_value = selected
        elif row_kind_value is not None and row_kind_value != selected:
            raise MetricContractValidationError(
                f"Công thức chỉ tính các dòng “{selected}”, nên loại dòng của metric phải là “{selected}”."
            )
    mixed = row_kind_column is not None and len(set(grains.values())) > 1
    if mixed and row_kind_value is None and (grain or time_window):
        raise MetricContractValidationError(
            "Dataset có nhiều loại dòng với grain khác nhau; chọn loại dòng metric dùng trước khi đặt grain hay mốc "
            "thời gian."
        )
    rows_grain = native_grain(row_kind_value, grains)

    # Grain và khoảng thời gian
    if grain is not None and grain not in READ_GRAINS:
        raise MetricContractValidationError(f"Grain phải là một trong: {', '.join(READ_GRAINS)}.")
    if grain and rows_grain and GRAINS.index(grain) < GRAINS.index(rows_grain):
        raise MetricContractValidationError(
            f"Grain “{grain}” mịn hơn dữ liệu metric dùng (grain “{rows_grain}”); chọn “{rows_grain}” hoặc thô hơn."
        )
    if time_window is not None:
        match = TIME_WINDOW.match(time_window)
        if match is None:
            raise MetricContractValidationError(
                "Khoảng thời gian phải có dạng last_<n>_<đơn vị>, current_<đơn vị>, previous_<đơn vị> hoặc "
                "<đơn vị>_to_date, ví dụ last_7_day hay month_to_date."
            )
        unit = match.group("last_unit") or match.group("unit") or match.group("to_date_unit")
        if rows_grain and rows_grain != "instant" and GRAINS.index(unit) < GRAINS.index(rows_grain):
            raise MetricContractValidationError(
                f"Khoảng thời gian tính theo “{unit}” mịn hơn dữ liệu metric dùng (grain “{rows_grain}”)."
            )
    if time_anchor is not None and time_anchor not in TIME_ANCHORS:
        raise MetricContractValidationError(
            "Mốc tính phải là now (thời điểm hiện tại) hoặc latest_data (mốc dữ liệu mới nhất)."
        )
    time_anchor = (time_anchor or "now") if time_window else None

    # Cột thời gian
    if time_column is None and (grain or time_window):
        time_column = context.time_column
    if time_column is not None and time_column not in context.temporal_columns:
        raise MetricContractValidationError(
            f"Cột thời gian “{time_column}” phải là cột ngày hoặc ngày giờ lọc được của dataset."
        )
    if time_column is None and (grain or time_window):
        raise MetricContractValidationError("Chọn cột thời gian cho grain và mốc thời gian của metric.")

    # Bộ lọc mặc định
    if len(raw_filters) > MAX_DEFAULT_FILTERS:
        raise MetricContractValidationError(f"Metric có tối đa {MAX_DEFAULT_FILTERS} bộ lọc mặc định.")
    default_filters = []
    for item in raw_filters:
        checked = checked_query_filter(columns, item)
        if checked["col"] in {time_column, context.time_column}:
            raise MetricContractValidationError(
                "Lọc theo thời gian bằng khoảng thời gian của metric, không bằng bộ lọc mặc định."
            )
        if checked["col"] == row_kind_column:
            raise MetricContractValidationError("Chọn loại dòng ở mục loại dòng, không bằng bộ lọc mặc định.")
        if any(existing["column"] == checked["col"] for existing in default_filters):
            raise MetricContractValidationError("Mỗi cột chỉ có một bộ lọc mặc định.")
        default_filters.append({"column": checked["col"], "operator": checked["op"], "value": checked["val"]})

    return MetricQueryDefaults(
        grain=grain,
        row_kind_value=row_kind_value,
        time_column=time_column,
        time_window=time_window,
        time_anchor=time_anchor,
        default_filters=tuple(default_filters),
        row_kind_column=row_kind_column if row_kind_value else None,
        native_grain=rows_grain,
    )


def checked_query_filter(columns: dict[str, Any], item: Any) -> dict[str, Any]:
    """Một bộ lọc `{column, operator, value}` đổi sang dạng ChartData, đã kiểm tra cột và kiểu giá trị."""
    if not isinstance(item, dict) or set(item) != {"column", "operator", "value"}:
        raise MetricContractValidationError("Mỗi bộ lọc cần đủ column, operator và value.")
    operator = item["operator"]
    if operator not in FILTER_OPERATORS:
        raise MetricContractValidationError(f"Phép so sánh “{operator}” không được hỗ trợ.")
    value = item["value"]
    is_membership_operator = operator in {"IN", "NOT IN"}
    if is_membership_operator != isinstance(value, list):
        raise MetricContractValidationError("IN và NOT IN cần một danh sách giá trị; các phép khác cần một giá trị.")
    values = value if is_membership_operator else [value]
    if not values or len(values) > MAX_FILTER_VALUES or any(not _scalar_filter_value(entry) for entry in values):
        raise MetricContractValidationError(
            f"Giá trị lọc phải có, tối đa {MAX_FILTER_VALUES} giá trị, mỗi giá trị tối đa "
            f"{MAX_FILTER_STRING_LENGTH} ký tự."
        )
    name = query_column(columns, item["column"], "filterable")
    _check_value_type(columns[name], values)
    return {"col": name, "op": operator, "val": value}


def query_column(columns: dict[str, Any], name: Any, capability: str) -> str:
    """Tên cột còn dùng được để `groupby` hoặc `filterable` khi chạy metric."""
    if not isinstance(name, str) or name not in columns:
        raise MetricContractValidationError(f"Dataset không có cột “{name}”.")
    column = columns[name]
    if getattr(column, "is_active", None) is not True or getattr(column, capability, None) is not True:
        action = "nhóm" if capability == "groupby" else "lọc"
        raise MetricContractValidationError(f"Cột “{name}” không được dùng để {action} khi chạy metric.")
    if getattr(column, "expression", None):
        raise MetricContractValidationError(f"Cột “{name}” là cột tính toán nên không dùng được khi chạy metric.")
    return name


# -------------------------APPLY--------------------------
def applied_query_defaults(
    defaults: MetricQueryDefaults | None,
    filtered_columns: set[str],
    dimensions: list[str],
    requested_grain: Any,
    apply_defaults: bool,
    latest_time: Callable[[list[dict[str, Any]]], Any] | None = None,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """Bộ lọc và grain mà giá trị mặc định thêm vào truy vấn, kèm mô tả những gì đã áp.

    Bộ lọc người gọi gửi trên một cột thắng giá trị mặc định trên cột đó; `apply_defaults` False bỏ qua tất cả.
    `latest_time(filters)` đọc mốc dữ liệu mới nhất, cho khoảng thời gian tính từ `latest_data`.
    """
    time_column = defaults.time_column if defaults else None
    if requested_grain is not None:
        if requested_grain not in READ_GRAINS:
            raise MetricContractValidationError(f"time_grain phải là một trong: {', '.join(READ_GRAINS)}.")
        if time_column is None or time_column not in dimensions:
            raise MetricContractValidationError("time_grain cần chiều phân tích là cột thời gian của metric.")
        rows_grain = defaults.native_grain if defaults else None
        if rows_grain and GRAINS.index(requested_grain) < GRAINS.index(rows_grain):
            raise MetricContractValidationError(
                f"time_grain “{requested_grain}” mịn hơn dữ liệu của metric (grain “{rows_grain}”)."
            )
    if defaults is None or not apply_defaults:
        applied = {"filters": [], "time_window": None, "time_grain": requested_grain} if requested_grain else None
        return [], requested_grain, applied

    applied_filters: list[dict[str, Any]] = []
    if defaults.row_kind_column and defaults.row_kind_value and defaults.row_kind_column not in filtered_columns:
        row_kind = {"column": defaults.row_kind_column, "operator": "==", "value": defaults.row_kind_value}
        applied_filters.append({**row_kind, "source": "row_kind"})
    for item in defaults.default_filters:
        if item["column"] not in filtered_columns:
            applied_filters.append({**item, "source": "default"})
    window = None
    if defaults.time_window and time_column and time_column not in filtered_columns:
        reference = None
        if defaults.time_anchor == "latest_data" and latest_time is not None:
            reference = reference_moment(latest_time(_chart_filters(applied_filters)))
        reference = reference or now or current_moment()
        start, end, end_included = time_window_bounds(defaults.time_window, reference)
        applied_filters += [
            {"column": time_column, "operator": ">=", "value": _bound_text(start), "source": "time_window"},
            {
                "column": time_column,
                "operator": "<=" if end_included else "<",
                "value": _bound_text(end),
                "source": "time_window",
            },
        ]
        window = {
            "window": defaults.time_window,
            "anchor": defaults.time_anchor,
            "column": time_column,
            "reference": reference.isoformat(),
            "start": _bound_text(start),
            "end": _bound_text(end),
            "end_included": end_included,
        }
    grain = requested_grain or (defaults.grain if time_column in dimensions else None)
    applied = {"filters": applied_filters, "time_window": window, "time_grain": grain}
    return _chart_filters(applied_filters), grain, applied


def time_window_bounds(window: str, reference: datetime) -> tuple[datetime, datetime, bool]:
    """Điểm đầu, điểm cuối của khoảng thời gian và điểm cuối có nằm trong khoảng không.

    `last_<n>_<đơn vị>` kết thúc ở đơn vị chứa `reference`; `current_` là cả đơn vị đó, `previous_` là đơn vị trước;
    `<đơn vị>_to_date` chạy từ đầu đơn vị tới chính `reference`.
    """
    match = TIME_WINDOW.match(window)
    if match is None:
        raise MetricContractValidationError("Khoảng thời gian của metric không hợp lệ.")
    if match.group("last_unit"):
        unit = match.group("last_unit")
        end = _shifted(_floor(reference, unit), unit, 1)
        return _shifted(end, unit, -int(match.group("count"))), end, False
    if match.group("to_date_unit"):
        return _floor(reference, match.group("to_date_unit")), reference, True
    unit = match.group("unit")
    start = _floor(reference, unit)
    if match.group("mode") == "previous":
        start = _shifted(start, unit, -1)
    return start, _shifted(start, unit, 1), False


def reference_moment(value: Any) -> datetime | None:
    """Mốc mới nhất ChartData trả về, đổi thành datetime không múi giờ; None nếu rỗng hoặc không đọc được."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = iso_moment(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:19]).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def current_moment() -> datetime:
    """Giờ hiện tại theo giờ Việt Nam, như kho dữ liệu lưu."""
    return datetime.now(tz=DATA_TIMEZONE).replace(tzinfo=None)


def time_axis_column(column_name: str, grain: str) -> dict[str, Any]:
    """Cột thời gian gom theo `grain`, dạng trục x của Superset (BASE_AXIS kèm timeGrain)."""
    return {
        "label": column_name,
        "sqlExpression": column_name,
        "expressionType": "SQL",
        "columnType": "BASE_AXIS",
        "timeGrain": TIME_GRAIN_DURATIONS[grain],
    }


# -------------------------HELPERS------------------------
def _floor(moment: datetime, unit: str) -> datetime:
    """Đầu giờ, ngày, tuần (thứ Hai), tháng, quý hoặc năm chứa `moment`."""
    if unit == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if unit == "day":
        return day
    if unit == "week":
        return day - timedelta(days=day.weekday())
    if unit == "month":
        return day.replace(day=1)
    if unit == "quarter":
        return day.replace(month=3 * ((day.month - 1) // 3) + 1, day=1)
    return day.replace(month=1, day=1)


def _shifted(moment: datetime, unit: str, count: int) -> datetime:
    """`moment` (đầu một đơn vị) dời đi `count` đơn vị."""
    if unit in ("hour", "day", "week"):
        return moment + timedelta(**{f"{unit}s": count})
    month_index = moment.year * 12 + moment.month - 1 + count * {"month": 1, "quarter": 3, "year": 12}[unit]
    return moment.replace(year=month_index // 12, month=month_index % 12 + 1)


def _bound_text(moment: datetime) -> str:
    """Ngày dạng YYYY-MM-DD, mốc khác kèm giờ, như bộ lọc thời gian của Superset đọc."""
    if moment.time() == datetime.min.time():
        return moment.strftime("%Y-%m-%d")
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _grains_on(dataset_ids: list[int]) -> dict[int, dict[str | None, str]]:
    grains: dict[int, dict[str | None, str]] = {}
    for grain in dataset_grain_repository().read_by_datasets(dataset_ids):
        grains.setdefault(grain.dataset_id, {})[grain.row_kind_value] = grain.grain
    return grains


def _chart_filters(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"col": item["column"], "op": item["operator"], "val": item["value"]} for item in items]


def _optional_text(body: dict[str, Any], field: str) -> str | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 255:
        raise MetricContractValidationError(f"{field} phải là văn bản tối đa 255 ký tự hoặc null.")
    return value.strip() or None


def _scalar_filter_value(value: Any) -> bool:
    if isinstance(value, str):
        return len(value) <= MAX_FILTER_STRING_LENGTH
    return isinstance(value, (int, float, bool))


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(value)
    except ValueError:
        return False
    return True


def _is_moment(value: Any) -> bool:
    """Ngày hoặc ngày giờ có thật, viết theo dạng frontend nhận."""
    match = MOMENT_TEXT.match(value.strip()) if isinstance(value, str) else None
    if match is None:
        return False
    day, hour, minute, second = match.groups()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return False
    return hour is None or (int(hour) < 24 and int(minute) < 60 and int(second or 0) < 60)


def _check_value_type(column: Any, values: list[Any]) -> None:
    """Báo lỗi khi giá trị lọc không đọc được theo kiểu của cột: ngày, ngày giờ hoặc số."""
    column_type = str(getattr(column, "type", None) or "")
    label = getattr(column, "verbose_name", None) or getattr(column, "column_name", "")
    numeric = bool(NUMERIC_TYPE.search(column_type))
    # A date column Superset reads from a numeric epoch (`is_dttm` on a number type) takes numbers.
    if TEMPORAL_TYPE.search(column_type) or (getattr(column, "is_dttm", False) and not numeric):
        if not all(_is_moment(value) for value in values):
            raise MetricContractValidationError(
                f"Giá trị lọc của cột {label} phải là ngày dạng YYYY-MM-DD hoặc ngày giờ YYYY-MM-DD HH:MM:SS."
            )
    elif numeric and not all(_is_number(value) for value in values):
        raise MetricContractValidationError(f"Giá trị lọc của cột {label} phải là số.")
