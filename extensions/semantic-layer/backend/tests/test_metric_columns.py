import pytest

from text_to_bi.superset_semantic_layer.modules.business_model.services.metric_columns import metric_columns

COLUMNS = ["loai_quan_sat", "nhiet_do_c", "tong_luong_mua_mm", "thanh_pho_id", "Nhiet Do"]


def roles(expression: str) -> dict[str, str] | None:
    result = metric_columns(expression, COLUMNS, "postgres")
    return None if result is None else {column["name"]: column["role"] for column in result}


def test_case_condition_is_a_filter_and_the_aggregated_value_a_measure():
    assert roles("AVG(CASE WHEN loai_quan_sat = 'DU_BAO_GIO' THEN nhiet_do_c END)") == {
        "loai_quan_sat": "filter",
        "nhiet_do_c": "measure",
    }


def test_count_of_a_condition_has_only_filters():
    expression = "COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0 THEN 1 END)"
    assert roles(expression) == {"loai_quan_sat": "filter", "tong_luong_mua_mm": "filter"}


def test_filter_clause_and_window_partition_are_filters():
    assert roles("SUM(tong_luong_mua_mm) FILTER (WHERE loai_quan_sat = 'X')") == {
        "loai_quan_sat": "filter",
        "tong_luong_mua_mm": "measure",
    }
    assert roles("SUM(nhiet_do_c) OVER (PARTITION BY thanh_pho_id ORDER BY loai_quan_sat)") == {
        "loai_quan_sat": "filter",
        "nhiet_do_c": "measure",
        "thanh_pho_id": "filter",
    }


def test_a_column_used_both_ways_is_a_measure():
    assert roles("SUM(CASE WHEN nhiet_do_c > 0 THEN nhiet_do_c END)") == {"nhiet_do_c": "measure"}


def test_unknown_names_are_dropped_and_names_match_ignoring_case():
    assert roles('SUM(NHIET_DO_C) + SUM(not_a_column) + AVG("Nhiet Do")') == {
        "nhiet_do_c": "measure",
        "Nhiet Do": "measure",
    }


def test_count_star_uses_no_column_and_unparseable_sql_gives_none():
    assert roles("COUNT(*)") == {}
    assert roles("SUM(nhiet_do_c) +* FROM") is None


def test_simple_case_subject_is_a_filter():
    assert roles("SUM(CASE loai_quan_sat WHEN 'A' THEN tong_luong_mua_mm ELSE 0 END)") == {
        "loai_quan_sat": "filter",
        "tong_luong_mua_mm": "measure",
    }


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("COUNT(DISTINCT thanh_pho_id)", {"thanh_pho_id": "measure"}),
        (
            "SUM(CASE WHEN loai_quan_sat = 'A' THEN tong_luong_mua_mm ELSE nhiet_do_c END)",
            {"loai_quan_sat": "filter", "tong_luong_mua_mm": "measure", "nhiet_do_c": "measure"},
        ),
        ("COALESCE(SUM(NULLIF(nhiet_do_c, 0)), 0)", {"nhiet_do_c": "measure"}),
        (
            "SUM(CAST(nhiet_do_c AS DECIMAL(10, 2))) + AVG(tong_luong_mua_mm::numeric)",
            {"nhiet_do_c": "measure", "tong_luong_mua_mm": "measure"},
        ),
        (
            "100.0 * SUM(tong_luong_mua_mm) / NULLIF(COUNT(DISTINCT thanh_pho_id), 0)",
            {"tong_luong_mua_mm": "measure", "thanh_pho_id": "measure"},
        ),
        ("ROUND(AVG(ABS(nhiet_do_c)), 1)", {"nhiet_do_c": "measure"}),
        (
            "COUNT(DISTINCT UPPER(TRIM(loai_quan_sat)) || '-' || CAST(thanh_pho_id AS TEXT))",
            {"loai_quan_sat": "measure", "thanh_pho_id": "measure"},
        ),
        (
            "MAX(DATE_TRUNC('day', loai_quan_sat)) - MIN(EXTRACT(YEAR FROM nhiet_do_c))",
            {"loai_quan_sat": "measure", "nhiet_do_c": "measure"},
        ),
        ("PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY nhiet_do_c)", {"nhiet_do_c": "measure"}),
        ('SUM(weather.nhiet_do_c) + MAX(public.weather."Nhiet Do")', {"nhiet_do_c": "measure", "Nhiet Do": "measure"}),
        (
            "COUNT(*) FILTER (WHERE loai_quan_sat IN ('A', 'B') AND nhiet_do_c IS NOT NULL)",
            {"loai_quan_sat": "filter", "nhiet_do_c": "filter"},
        ),
    ],
)
def test_every_sql_form_finds_its_input_columns(expression, expected):
    assert roles(expression) == expected


def test_an_if_function_condition_is_a_filter():
    result = metric_columns("SUM(IF(tong_luong_mua_mm > 0, nhiet_do_c, 0))", COLUMNS, "mysql")
    assert result == [{"name": "nhiet_do_c", "role": "measure"}, {"name": "tong_luong_mua_mm", "role": "filter"}]


def test_templated_expressions_read_the_columns_of_every_branch():
    expression = "SUM(nhiet_do_c) {% if filter_values('city') %}+ SUM(tong_luong_mua_mm){% endif %} * {{ scale }}"
    assert roles(expression) == {"nhiet_do_c": "measure", "tong_luong_mua_mm": "measure"}
