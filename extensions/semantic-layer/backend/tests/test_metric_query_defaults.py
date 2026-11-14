from datetime import datetime
from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.metric_management.exceptions import MetricContractValidationError
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_contract import metric_contract_hash, metric_contract_state, parse_contract_metric
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_data import build_latest_time_payload
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_execute import (
    execute_approved_chart_query,
    planned_metric_chart,
)
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_formula import formula_row_kinds
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_query_defaults import (
    DatasetTimeContext,
    MetricQueryDefaults,
    checked_query_defaults,
    reference_moment,
    stored_query_defaults,
    time_window_bounds,
)

# Dataset 12's rows: hourly and daily forecasts and irregular current observations in one table.
GRAINS = {"DU_BAO_GIO": "hour", "DU_BAO_NGAY": "day", "HIEN_TAI": "instant"}
RAIN = "SUM(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' THEN tong_luong_mua_mm END)"


def _column(name, **flags):
    values = {"is_active": True, "expression": None, "groupby": True, "filterable": True, "is_dttm": False, **flags}
    return SimpleNamespace(column_name=name, **values)


def _weather():
    columns = [
        _column("thoi_diem_quan_sat", is_dttm=True),
        _column("loai_quan_sat"),
        _column("thanh_pho_key"),
        _column("tong_luong_mua_mm"),
        _column("ghi_chu", filterable=False),
    ]
    metric = SimpleNamespace(id=4, metric_name="tong_luong_mua", expression=RAIN)
    dataset = SimpleNamespace(
        id=12, columns=columns, metrics=[metric], sql=None, catalog=None, schema="public",
        table_name="fact_tong_hop_thoi_tiet", database=SimpleNamespace(id=1, database_name="warehouse"),
    )
    return dataset, metric


def _checked(body, expression=RAIN, row_kind_column="loai_quan_sat", grains=None):
    dataset, _ = _weather()
    formula = parse_contract_metric(expression)
    return checked_query_defaults(
        body,
        {column.column_name: column for column in dataset.columns},
        DatasetTimeContext("thoi_diem_quan_sat", row_kind_column, GRAINS if grains is None else grains, {"thoi_diem_quan_sat"}),
        formula_row_kinds=formula_row_kinds(formula, row_kind_column),
    )


def test_formula_row_kinds_reads_the_row_kind_condition():
    formula = parse_contract_metric(RAIN)
    assert formula_row_kinds(formula, "loai_quan_sat") == {"DU_BAO_NGAY"}
    assert formula_row_kinds(formula, None) == set()


def test_defaults_take_the_row_kind_from_the_formula_and_the_time_column_from_the_dataset():
    defaults = _checked({"grain": "week", "time_window": "last_7_day"})
    assert defaults.row_kind_value == "DU_BAO_NGAY" and defaults.native_grain == "day"
    assert defaults.time_column == "thoi_diem_quan_sat" and defaults.time_anchor == "now"
    assert defaults.row_kind_column == "loai_quan_sat"
    assert _checked({}).is_empty()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"grain": "hour"}, "mịn hơn"),
        ({"grain": "minute"}, "Grain phải là"),
        ({"row_kind_value": "DU_BAO_GIO"}, "DU_BAO_NGAY"),
        ({"row_kind_value": "KHAC"}, "chưa được khai báo grain"),
        ({"time_window": "last_week"}, "last_<n>_<đơn vị>"),
        ({"time_window": "last_3_hour"}, "mịn hơn"),
        ({"time_window": "current_month", "time_anchor": "yesterday"}, "latest_data"),
        ({"time_column": "loai_quan_sat"}, "cột ngày hoặc ngày giờ"),
        ({"default_filters": [{"column": "ghi_chu", "operator": "==", "value": "x"}]}, "không được dùng để lọc"),
        ({"default_filters": [{"column": "loai_quan_sat", "operator": "==", "value": "x"}]}, "loại dòng"),
        ({"default_filters": [{"column": "thoi_diem_quan_sat", "operator": ">=", "value": "2026-10-01"}]}, "thời gian"),
        ({"surprise": 1}, "Chỉ gửi"),
    ],
)
def test_defaults_are_checked_against_the_dataset_grains_and_formula(body, message):
    with pytest.raises(MetricContractValidationError, match=message):
        _checked(body)


def test_a_metric_over_every_row_kind_of_a_mixed_table_must_choose_one():
    with pytest.raises(MetricContractValidationError, match="nhiều loại dòng"):
        _checked({"grain": "day"}, expression="AVG(tong_luong_mua_mm)")
    chosen = _checked({"grain": "day", "row_kind_value": "DU_BAO_GIO"}, expression="AVG(tong_luong_mua_mm)")
    assert chosen.native_grain == "hour"


def test_a_dataset_without_row_kinds_takes_its_single_grain():
    plain_sum = "SUM(tong_luong_mua_mm)"
    defaults = _checked({"grain": "month"}, expression=plain_sum, row_kind_column=None, grains={None: "day"})
    assert defaults.row_kind_value is None and defaults.native_grain == "day"
    with pytest.raises(MetricContractValidationError, match="cột phân loại dòng"):
        _checked({"row_kind_value": "A"}, expression="SUM(tong_luong_mua_mm)", row_kind_column=None, grains={})


def test_stored_defaults_round_trip_through_the_definition_row():
    defaults = _checked(
        {"grain": "day", "time_window": "month_to_date", "time_anchor": "latest_data",
         "default_filters": [{"column": "thanh_pho_key", "operator": "IN", "value": [1, 2]}]}
    )
    row = SimpleNamespace(
        grain=defaults.grain, row_kind_value=defaults.row_kind_value, time_column=defaults.time_column,
        time_window=defaults.time_window, time_anchor=defaults.time_anchor,
        default_filters=defaults.stored_values()["default_filters"],
    )
    context = DatasetTimeContext("thoi_diem_quan_sat", "loai_quan_sat", GRAINS, {"thoi_diem_quan_sat"})
    assert stored_query_defaults(row, context) == defaults
    assert stored_query_defaults(SimpleNamespace(grain=None, row_kind_value=None, time_column=None, time_window=None, time_anchor=None, default_filters=None), context) is None
    assert stored_query_defaults(None, context) is None


@pytest.mark.parametrize(
    ("window", "start", "end", "included"),
    [
        ("last_7_day", datetime(2026, 10, 20), datetime(2026, 10, 27), False),
        ("last_24_hour", datetime(2026, 10, 25, 15), datetime(2026, 10, 26, 15), False),
        ("current_week", datetime(2026, 10, 26), datetime(2026, 11, 2), False),
        ("previous_month", datetime(2026, 9, 1), datetime(2026, 10, 1), False),
        ("current_quarter", datetime(2026, 10, 1), datetime(2027, 1, 1), False),
        ("previous_year", datetime(2025, 1, 1), datetime(2026, 1, 1), False),
        ("month_to_date", datetime(2026, 10, 1), datetime(2026, 10, 26, 14, 30), True),
    ],
)
def test_time_windows_count_from_the_reference_moment(window, start, end, included):
    assert time_window_bounds(window, datetime(2026, 10, 26, 14, 30)) == (start, end, included)


def test_reference_moment_reads_what_chartdata_returns():
    assert reference_moment(datetime(2026, 11, 1, 23)) == datetime(2026, 11, 1, 23)
    assert reference_moment("2026-11-01T23:00:00") == datetime(2026, 11, 1, 23)
    assert reference_moment("Sun, 01 Nov 2026 23:00:00 GMT") == datetime(2026, 11, 1, 23)
    assert reference_moment(None) is None


def _defaults(**values):
    return MetricQueryDefaults(
        **{
            "grain": "day", "row_kind_value": "DU_BAO_NGAY", "time_column": "thoi_diem_quan_sat",
            "time_window": "last_7_day", "time_anchor": "now", "row_kind_column": "loai_quan_sat",
            "native_grain": "day",
            "default_filters": ({"column": "thanh_pho_key", "operator": "==", "value": 1},),
            **values,
        }
    )


def test_execution_applies_the_row_kind_default_filters_window_and_grain():
    dataset, metric = _weather()
    query = {"dimensions": ["thoi_diem_quan_sat"], "filters": []}
    payload, applied = planned_metric_chart(dataset, metric, query, 100, _defaults(), now=datetime(2026, 10, 26, 9))

    chart_query = payload["queries"][0]
    assert chart_query["columns"] == [
        {"label": "thoi_diem_quan_sat", "sqlExpression": "thoi_diem_quan_sat", "expressionType": "SQL",
         "columnType": "BASE_AXIS", "timeGrain": "P1D"}
    ]
    assert chart_query["filters"] == [
        {"col": "loai_quan_sat", "op": "==", "val": "DU_BAO_NGAY"},
        {"col": "thanh_pho_key", "op": "==", "val": 1},
        {"col": "thoi_diem_quan_sat", "op": ">=", "val": "2026-10-20"},
        {"col": "thoi_diem_quan_sat", "op": "<", "val": "2026-10-27"},
    ]
    assert applied["time_grain"] == "day" and applied["time_window"]["start"] == "2026-10-20"
    assert [item["source"] for item in applied["filters"]] == ["row_kind", "default", "time_window", "time_window"]


def test_a_caller_filter_overrides_the_default_on_its_column():
    dataset, metric = _weather()
    query = {
        "dimensions": ["thanh_pho_key"],
        "filters": [
            {"column": "thanh_pho_key", "operator": "IN", "value": [2, 3]},
            {"column": "thoi_diem_quan_sat", "operator": ">=", "value": "2026-10-01"},
        ],
    }
    payload, applied = planned_metric_chart(dataset, metric, query, 100, _defaults(), now=datetime(2026, 10, 26))

    assert payload["queries"][0]["columns"] == ["thanh_pho_key"]
    assert payload["queries"][0]["filters"] == [
        {"col": "thanh_pho_key", "op": "IN", "val": [2, 3]},
        {"col": "thoi_diem_quan_sat", "op": ">=", "val": "2026-10-01"},
        {"col": "loai_quan_sat", "op": "==", "val": "DU_BAO_NGAY"},
    ]
    assert applied["time_window"] is None and applied["time_grain"] is None


def test_apply_defaults_false_runs_the_bare_metric_and_time_grain_overrides_the_grain():
    dataset, metric = _weather()
    bare, applied = planned_metric_chart(
        dataset, metric, {"dimensions": ["thoi_diem_quan_sat"], "apply_defaults": False}, 100, _defaults()
    )
    assert bare["queries"][0]["filters"] == [] and bare["queries"][0]["columns"] == ["thoi_diem_quan_sat"]
    assert applied is None

    monthly, applied = planned_metric_chart(
        dataset, metric, {"dimensions": ["thoi_diem_quan_sat"], "time_grain": "month"}, 100, _defaults(),
        now=datetime(2026, 10, 26),
    )
    assert monthly["queries"][0]["columns"][0]["timeGrain"] == "P1M" and applied["time_grain"] == "month"


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({"dimensions": ["thoi_diem_quan_sat"], "time_grain": "hour"}, "mịn hơn"),
        ({"dimensions": [], "time_grain": "day"}, "chiều phân tích"),
        ({"dimensions": [], "apply_defaults": "no"}, "apply_defaults"),
    ],
)
def test_execution_rejects_a_time_grain_finer_than_the_rows_or_without_a_time_dimension(query, message):
    dataset, metric = _weather()
    with pytest.raises(MetricContractValidationError, match=message):
        planned_metric_chart(dataset, metric, query, 100, _defaults())


def test_a_window_anchored_to_the_latest_data_counts_back_from_it():
    dataset, metric = _weather()
    asked = []

    def latest(filters):
        asked.append(filters)
        return datetime(2026, 11, 1, 23)

    payload, applied = planned_metric_chart(
        dataset, metric, {"dimensions": []}, 100, _defaults(time_anchor="latest_data"), latest, datetime(2026, 10, 1)
    )
    assert asked == [[{"col": "loai_quan_sat", "op": "==", "val": "DU_BAO_NGAY"},
                      {"col": "thanh_pho_key", "op": "==", "val": 1}]]
    assert applied["time_window"]["reference"] == "2026-11-01T23:00:00"
    assert payload["queries"][0]["filters"][-2:] == [
        {"col": "thoi_diem_quan_sat", "op": ">=", "val": "2026-10-26"},
        {"col": "thoi_diem_quan_sat", "op": "<", "val": "2026-11-02"},
    ]


def test_the_latest_moment_is_one_max_under_the_default_filters():
    dataset, _ = _weather()
    filters = [{"col": "loai_quan_sat", "op": "==", "val": "DU_BAO_NGAY"}]
    query = build_latest_time_payload(dataset, "thoi_diem_quan_sat", filters)["queries"][0]
    assert query["metrics"][0]["sqlExpression"] == "MAX(thoi_diem_quan_sat)"
    assert query["filters"] == filters and query["row_limit"] == 1
    assert build_latest_time_payload(dataset, "thoi diem; DROP", filters) is None


def test_changing_the_defaults_outdates_an_approval_like_a_formula_edit():
    dataset, metric = _weather()
    approved_defaults = _defaults()
    contract = SimpleNamespace(
        dataset_id=12, metric_id=4, status="approved",
        expression_hash=metric_contract_hash(dataset, metric, approved_defaults),
    )
    assert metric_contract_state(contract, dataset, metric, approved_defaults) == "approved"
    assert metric_contract_state(contract, dataset, metric, _defaults(grain="week")) == "outdated"
    assert metric_contract_state(contract, dataset, metric, _defaults(native_grain="hour")) == "outdated"
    assert metric_contract_state(contract, dataset, metric, None) == "outdated"
    # A metric without defaults keeps the hash it had before they existed.
    assert metric_contract_hash(dataset, metric, MetricQueryDefaults()) == metric_contract_hash(dataset, metric)

    with pytest.raises(Exception, match="chưa được duyệt"):
        execute_approved_chart_query(contract, dataset, metric, {}, 100, lambda payload: {}, defaults=None)
    result = execute_approved_chart_query(
        contract, dataset, metric, {}, 100, lambda payload: {"data": []}, defaults=approved_defaults
    )
    assert result["applied_defaults"]["filters"][0]["source"] == "row_kind"
