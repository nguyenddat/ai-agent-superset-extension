from datetime import date
from types import SimpleNamespace

from text_to_bi.superset_semantic_layer.modules.semantic_query.services.members import (
    MAX_MEMBERS,
    build_members_payload,
    build_time_range_payload,
    labelled_key_columns,
    labels_from_rows,
    members_from_rows,
    stored_label_candidates,
    temporal_columns,
    time_ranges_from_rows,
)


def _column(name, expression=None, groupby=True, filterable=True, is_active=True, is_dttm=False):
    return SimpleNamespace(
        column_name=name, expression=expression, groupby=groupby, filterable=filterable, is_active=is_active,
        is_dttm=is_dttm,
    )


def _dataset(columns):
    return SimpleNamespace(id=12, table_name="fact_weather", columns=columns)


def test_a_calculated_column_reading_one_physical_column_labels_it():
    dataset = _dataset([
        _column("city_key"),
        _column("day_key"),
        _column("city_name", "(SELECT d.name FROM dim_city d WHERE d.city_key = fact_weather.city_key)"),
        _column("city_and_day", "fact_weather.city_key || fact_weather.day_key"),
        _column("hidden_name", "(SELECT 1 WHERE fact_weather.city_key = 1)", groupby=False),
        _column("constant", "'x'"),
    ])

    assert labelled_key_columns(dataset) == [("city_key", "city_name")]


def test_the_payload_reads_only_the_key_and_label_with_a_bounded_row_limit():
    payload = build_members_payload(_dataset([]), "city_key", ["city_name"])

    query = payload["queries"][0]
    assert payload["datasource"] == {"id": 12, "type": "table"}
    assert query["columns"] == ["city_key", "city_name"]
    assert query["row_limit"] == MAX_MEMBERS + 1


def test_members_are_unique_labelled_pairs_sorted_by_label():
    rows = [
        {"city_key": 2, "city_name": "Hue"},
        {"city_key": 1, "city_name": "Ha Noi"},
        {"city_key": 1, "city_name": "Ha Noi"},
        {"city_key": None, "city_name": "Unknown"},
        {"city_key": 3, "city_name": None},
    ]

    assert members_from_rows(rows, "city_key", "city_name") == [
        {"value": 1, "label": "Ha Noi"},
        {"value": 2, "label": "Hue"},
    ]


def test_a_key_column_is_offered_the_physical_text_columns_that_may_name_it():
    city_name, region, kind = _column("city_name"), _column("region"), _column("row_kind")
    for column in (city_name, region, kind):
        column.type = "VARCHAR(100)"
    observed_on = _column("observed_on", is_dttm=True)
    observed_on.type = "DATE"
    dataset = _dataset([
        _column("observation_id"), _column("city_key"), observed_on, city_name, region, kind,
        _column("label_lookup", "(SELECT 1)"),
    ])
    entries = {
        "observation_id": SimpleNamespace(semantic_role="key", is_fk=True, is_pk=False, is_unique=True),
        "city_key": SimpleNamespace(semantic_role="key", is_fk=True, is_pk=False, is_unique=False),
        "observed_on": SimpleNamespace(semantic_role="key", is_fk=True, is_pk=False, is_unique=False),
        "city_name": SimpleNamespace(semantic_role="dimension", is_fk=False, is_pk=False, is_unique=False),
    }

    assert stored_label_candidates(dataset, entries) == [("city_key", ["city_name", "region", "row_kind"])]
    assert build_members_payload(dataset, "city_key", ["city_name", "region"])["queries"][0]["columns"] == [
        "city_key", "city_name", "region",
    ]


def test_a_text_column_labels_a_key_only_when_the_data_gives_each_key_one_value():
    rows = [
        {"city_key": 1, "city_name": "Ha Noi", "region": "Dong Bac Bo", "row_kind": "HOURLY"},
        {"city_key": 1, "city_name": "Ha Noi", "region": "Dong Bac Bo", "row_kind": "DAILY"},
        {"city_key": 2, "city_name": "Hue", "region": "Bac Trung Bo", "row_kind": "HOURLY"},
    ]

    labelled = labels_from_rows(rows, "city_key", ["city_name", "region", "row_kind"])

    assert labelled == {
        "city_name": [{"value": 1, "label": "Ha Noi"}, {"value": 2, "label": "Hue"}],
        "region": [{"value": 2, "label": "Bac Trung Bo"}, {"value": 1, "label": "Dong Bac Bo"}],
    }
    assert labels_from_rows(rows * (MAX_MEMBERS // 2), "city_key", ["city_name"]) == {}


def test_the_date_range_is_read_for_physical_date_columns_only():
    dataset = _dataset([
        _column("day_key", is_dttm=True),
        _column("city_key"),
        _column("month", "date_trunc('month', fact_weather.day_key)", is_dttm=True),
        _column("odd name", is_dttm=True),
    ])

    columns = temporal_columns(dataset)
    metrics = build_time_range_payload(dataset, columns)["queries"][0]["metrics"]

    assert columns == ["day_key"]
    assert [metric["sqlExpression"] for metric in metrics] == ["MIN(day_key)", "MAX(day_key)"]


def test_a_date_range_reads_dates_timestamps_and_epoch_milliseconds():
    rows = [{"min__day_key": date(2026, 10, 12), "max__day_key": 1793491200000, "min__other": None}]

    assert time_ranges_from_rows(rows, ["day_key", "other"]) == [
        {"column": "day_key", "min": "2026-10-12", "max": "2026-11-01"},
    ]
