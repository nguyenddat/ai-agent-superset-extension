from types import SimpleNamespace

from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_validation import (
    metric_semantic_ineligibility,
)


def _entry(role, aggregations=None, unit=None):
    return SimpleNamespace(semantic_role=role, aggregations=aggregations, unit=unit)


def test_a_measure_needs_the_declared_role_and_allowed_aggregation():
    metric = SimpleNamespace(expression="SUM(rain_mm)")
    columns = {"rain_mm": _entry("dimension", '["SUM"]', "mm")}
    assert "vai trò measure" in metric_semantic_ineligibility(metric=metric, dataset=None, columns=columns, metric_unit="mm", grains={})
    columns["rain_mm"].semantic_role = "measure"
    columns["rain_mm"].aggregations = '["AVG"]'
    assert "chưa cho phép phép tổng hợp SUM" in metric_semantic_ineligibility(None, metric, columns, "mm", {})


def test_units_and_row_grain_must_fit_the_formula():
    metric = SimpleNamespace(expression="AVG(CASE WHEN row_kind = 'DAILY' THEN temperature END)")
    columns = {
        "row_kind": _entry("row_kind"),
        "temperature": _entry("measure", '["AVG"]', "°C"),
    }
    assert "đơn vị cột" in metric_semantic_ineligibility(None, metric, columns, "km/h", {"DAILY": "day"}, "row_kind")
    assert "chưa được khai báo grain" in metric_semantic_ineligibility(None, metric, columns, "°C", {}, "row_kind")
    assert metric_semantic_ineligibility(None, metric, columns, "°C", {"DAILY": "day"}, "row_kind") is None


def test_a_count_metric_cannot_claim_a_measure_unit():
    metric = SimpleNamespace(expression="COUNT(rows_seen)")
    assert "đơn vị count" in metric_semantic_ineligibility(None, metric, {"rows_seen": _entry("measure", '["COUNT"]')}, "mm", {})
