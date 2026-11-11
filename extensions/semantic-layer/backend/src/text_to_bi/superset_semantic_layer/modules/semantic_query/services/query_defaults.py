import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from ....common.utils.type_formatter import iso_moment
from ...data_dictionary.services.time_semantics import GRAINS
from ..exceptions import MetricContractValidationError

# A metric is read by the hour or coarser: `instant` rows have no regular step to group them by.
READ_GRAINS = GRAINS[1:]
# The period Superset groups a temporal column by for each grain (ChartData `timeGrain`); weeks start on Monday.
TIME_GRAIN_DURATIONS = {"hour": "PT1H", "day": "P1D", "week": "P1W", "month": "P1M", "quarter": "P3M", "year": "P1Y"}
TIME_ANCHORS = ("now", "latest_data")
_TIME_WINDOW = re.compile(
    r"^(?:last_(?P<count>[1-9][0-9]{0,2})_(?P<last_unit>hour|day|week|month|quarter|year)"
    r"|(?P<mode>current|previous)_(?P<unit>day|week|month|quarter|year)"
    r"|(?P<to_date_unit>day|week|month|quarter|year)_to_date)$"
)
# The warehouse stores Vietnam's wall-clock time (Asia/Bangkok, UTC+7) without a zone.
DATA_TIMEZONE = timezone(timedelta(hours=7))
MAX_DEFAULT_FILTERS = 10
FILTER_OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN")
MAX_FILTER_VALUES = 100
MAX_FILTER_STRING_LENGTH = 1024
QUERY_DEFAULT_FIELDS = ("grain", "row_kind_value", "time_column", "time_window", "time_anchor", "default_filters")


@dataclass(frozen=True)
class MetricQueryDefaults:
    """How a metric is read unless the caller says otherwise: its grain, time anchor and default filters.

    The first six fields are stored with the metric's business definition. `row_kind_column` and `native_grain` come
    from the dataset's data dictionary when the defaults are loaded, so a change there also changes the metric.
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


def query_column(columns: dict[str, Any], name: Any, capability: str) -> str:
    """A live column the metric query may use for `capability` (`groupby` or `filterable`)."""
    if not isinstance(name, str) or name not in columns:
        raise MetricContractValidationError(f"Dataset không có cột “{name}”.")
    column = columns[name]
    # These are the capability fields actually present on Superset TableColumn. Datasource/RLS access remains
    # ChartData's responsibility.
    if getattr(column, "is_active", None) is not True or getattr(column, capability, None) is not True:
        action = "nhóm" if capability == "groupby" else "lọc"
        raise MetricContractValidationError(f"Cột “{name}” không được dùng để {action} khi chạy metric.")
    if getattr(column, "expression", None):
        raise MetricContractValidationError(f"Cột “{name}” là cột tính toán nên không dùng được khi chạy metric.")
    return name


def checked_query_filter(columns: dict[str, Any], item: Any) -> dict[str, Any]:
    """One `{column, operator, value}` filter as a ChartData filter, checked against the live columns.

    A value must also fit the column's type, so a date column is never compared with text the database cannot read.
    """
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


def _scalar_filter_value(value: Any) -> bool:
    if isinstance(value, str):
        return len(value) <= MAX_FILTER_STRING_LENGTH
    return isinstance(value, (int, float, bool))


_TEMPORAL_TYPE = re.compile(r"DATE|TIME", re.IGNORECASE)
_NUMERIC_TYPE = re.compile(r"INT|FLOAT|DOUBLE|NUMERIC|DECIMAL|REAL|SERIAL|NUMBER", re.IGNORECASE)
_MOMENT_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")


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
    """A date or timestamp written as the frontend accepts it, the same on every Python version."""
    return isinstance(value, str) and _MOMENT_TEXT.match(value.strip()) is not None


def _check_value_type(column: Any, values: list[Any]) -> None:
    """Raise when a filter value cannot be read as the column's type: a date, a timestamp or a number.

    A date column Superset reads from a numeric epoch (`is_dttm` on a number type) takes numbers.
    """
    column_type = str(getattr(column, "type", None) or "")
    label = getattr(column, "verbose_name", None) or getattr(column, "column_name", "")
    numeric = bool(_NUMERIC_TYPE.search(column_type))
    if _TEMPORAL_TYPE.search(column_type) or (getattr(column, "is_dttm", False) and not numeric):
        if not all(_is_moment(value) for value in values):
            raise MetricContractValidationError(
                f"Giá trị lọc của cột {label} phải là ngày dạng YYYY-MM-DD hoặc ngày giờ YYYY-MM-DD HH:MM:SS."
            )
    elif numeric and not all(_is_number(value) for value in values):
        raise MetricContractValidationError(f"Giá trị lọc của cột {label} phải là số.")


def native_grain(row_kind_value: str | None, grains: dict[str | None, str]) -> str | None:
    """The grain of the rows a metric reads: its row kind's, or the dataset's only grain."""
    if row_kind_value is not None:
        return grains.get(row_kind_value)
    return next(iter(grains.values())) if len(grains) == 1 else None


def stored_query_defaults(
    definition: Any, row_kind_column: str | None, grains: dict[str | None, str]
) -> MetricQueryDefaults | None:
    """A metric's saved defaults with what the data dictionary says about its rows; None when it has none."""
    if definition is None:
        return None
    try:
        filters = json.loads(getattr(definition, "default_filters", None) or "[]")
    except (TypeError, ValueError):
        filters = []
    defaults = MetricQueryDefaults(
        grain=getattr(definition, "grain", None),
        row_kind_value=getattr(definition, "row_kind_value", None),
        time_column=getattr(definition, "time_column", None),
        time_window=getattr(definition, "time_window", None),
        time_anchor=getattr(definition, "time_anchor", None),
        default_filters=tuple(item for item in filters if isinstance(item, dict)),
    )
    if defaults.is_empty():
        return None
    return replace(
        defaults,
        row_kind_column=row_kind_column if defaults.row_kind_value else None,
        native_grain=native_grain(defaults.row_kind_value, grains),
    )


def stored_filters(defaults: MetricQueryDefaults) -> str | None:
    """The default filters as the definition row keeps them."""
    return json.dumps(list(defaults.default_filters), ensure_ascii=False) if defaults.default_filters else None


def _optional_text(body: dict[str, Any], field: str) -> str | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 255:
        raise MetricContractValidationError(f"{field} phải là văn bản tối đa 255 ký tự hoặc null.")
    return value.strip() or None


def _window_unit(window: str) -> str:
    match = _TIME_WINDOW.match(window)
    return match.group("last_unit") or match.group("unit") or match.group("to_date_unit")


def checked_query_defaults(
    body: Any,
    columns: dict[str, Any],
    *,
    temporal_columns: set[str],
    dataset_time_column: str | None,
    row_kind_column: str | None,
    grains: dict[str | None, str],
    formula_row_kinds: set[str],
) -> MetricQueryDefaults:
    """The defaults an administrator saves for a metric, checked against its dataset and formula.

    `temporal_columns` are the date and timestamp columns the metric can be filtered by; `grains` maps each row kind
    of the dataset (None for a dataset with one grain) to its grain; `formula_row_kinds` are the row kinds the formula
    selects. Raises MetricContractValidationError with a message for the administrator.
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

    if grain is not None and grain not in READ_GRAINS:
        raise MetricContractValidationError(f"Grain phải là một trong: {', '.join(READ_GRAINS)}.")
    if grain and rows_grain and GRAINS.index(grain) < GRAINS.index(rows_grain):
        raise MetricContractValidationError(
            f"Grain “{grain}” mịn hơn dữ liệu metric dùng (grain “{rows_grain}”); chọn “{rows_grain}” hoặc thô hơn."
        )
    if time_window is not None:
        if not _TIME_WINDOW.match(time_window):
            raise MetricContractValidationError(
                "Khoảng thời gian phải có dạng last_<n>_<đơn vị>, current_<đơn vị>, previous_<đơn vị> hoặc "
                "<đơn vị>_to_date, ví dụ last_7_day hay month_to_date."
            )
        unit = _window_unit(time_window)
        if rows_grain and rows_grain != "instant" and GRAINS.index(unit) < GRAINS.index(rows_grain):
            raise MetricContractValidationError(
                f"Khoảng thời gian tính theo “{unit}” mịn hơn dữ liệu metric dùng (grain “{rows_grain}”)."
            )
    if time_anchor is not None and time_anchor not in TIME_ANCHORS:
        raise MetricContractValidationError(
            "Mốc tính phải là now (thời điểm hiện tại) hoặc latest_data (mốc dữ liệu mới nhất)."
        )
    time_anchor = (time_anchor or "now") if time_window else None

    if time_column is None and (grain or time_window):
        time_column = dataset_time_column
    if time_column is not None and time_column not in temporal_columns:
        raise MetricContractValidationError(
            f"Cột thời gian “{time_column}” phải là cột ngày hoặc ngày giờ lọc được của dataset."
        )
    if time_column is None and (grain or time_window):
        raise MetricContractValidationError("Chọn cột thời gian cho grain và mốc thời gian của metric.")

    if len(raw_filters) > MAX_DEFAULT_FILTERS:
        raise MetricContractValidationError(f"Metric có tối đa {MAX_DEFAULT_FILTERS} bộ lọc mặc định.")
    default_filters = []
    for item in raw_filters:
        checked = checked_query_filter(columns, item)
        if checked["col"] in {time_column, dataset_time_column}:
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


def _floor(moment: datetime, unit: str) -> datetime:
    """The start of the hour, day, week (Monday), month, quarter or year holding `moment`."""
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
    """`moment`, the start of a unit, moved by `count` units."""
    if unit in ("hour", "day", "week"):
        return moment + timedelta(**{f"{unit}s": count})
    month_index = moment.year * 12 + moment.month - 1 + count * {"month": 1, "quarter": 3, "year": 12}[unit]
    return moment.replace(year=month_index // 12, month=month_index % 12 + 1)


def time_window_bounds(window: str, reference: datetime) -> tuple[datetime, datetime, bool]:
    """The first moment of the window, its end, and whether the end itself is inside it.

    `last_<n>_<unit>` ends with the unit holding `reference` (last_7_day is that day and the six before);
    `current_<unit>` is the whole unit holding it, `previous_<unit>` the one before, and `<unit>_to_date` runs from the
    start of its unit up to `reference` itself.
    """
    match = _TIME_WINDOW.match(window)
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


def _bound_text(moment: datetime) -> str:
    """A day as YYYY-MM-DD, any other moment with its time, as Superset's temporal filters read them."""
    if moment.time() == datetime.min.time():
        return moment.strftime("%Y-%m-%d")
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def reference_moment(value: Any) -> datetime | None:
    """The latest moment ChartData returned, as a datetime without zone; None when it is empty or unreadable."""
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
    return datetime.now(tz=DATA_TIMEZONE).replace(tzinfo=None)


def applied_query_defaults(
    defaults: MetricQueryDefaults | None,
    filtered_columns: set[str],
    dimensions: list[str],
    requested_grain: Any,
    apply_defaults: bool,
    latest_time: Callable[[list[dict[str, Any]]], Any] | None = None,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """The ChartData filters and time grain a metric's defaults add to a caller's query, and what was applied.

    A caller filter on a column overrides the default on that column: the row kind, a default filter or the time window.
    `apply_defaults` False skips them all. The metric's grain groups its time column when the query is split by it;
    `requested_grain` replaces it but may not be finer than the rows. `latest_time(filters)` reads the latest moment
    of the time column under the given ChartData filters, for a window anchored to the latest data.
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
        applied_filters.append(
            {"column": defaults.row_kind_column, "operator": "==", "value": defaults.row_kind_value,
             "source": "row_kind"}
        )
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
            {"column": time_column, "operator": "<=" if end_included else "<", "value": _bound_text(end),
             "source": "time_window"},
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


def _chart_filters(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"col": item["column"], "op": item["operator"], "val": item["value"]} for item in items]


def time_axis_column(column_name: str, grain: str) -> dict[str, Any]:
    """The time dimension grouped by `grain`, as Superset's own x-axis column (an adhoc BASE_AXIS with timeGrain)."""
    return {
        "label": column_name,
        "sqlExpression": column_name,
        "expressionType": "SQL",
        "columnType": "BASE_AXIS",
        "timeGrain": TIME_GRAIN_DURATIONS[grain],
    }
