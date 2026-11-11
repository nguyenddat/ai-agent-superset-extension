import pytest

from text_to_bi.superset_semantic_layer.modules.semantic_query.services.formula_reading import metric_pseudo_code

LABELS = {
    "loai_quan_sat": "Loại quan sát",
    "tong_luong_mua_mm": "Tổng lượng mưa (mm)",
    "nhiet_do_c": "Nhiệt độ (°C)",
    "thanh_pho_id": "Thành phố",
    "ngay": "Ngày",
}
RAINY_DAY_SHARE = (
    "100.0 * COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0 THEN 1 END)"
    " / NULLIF(COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' THEN 1 END), 0)"
)


def test_a_ratio_puts_its_divisor_on_a_line_of_its_own():
    assert metric_pseudo_code(RAINY_DAY_SHARE, LABELS) == (
        "100.0 × ĐẾM(NẾU [Loại quan sát] = “DU_BAO_NGAY” VÀ [Tổng lượng mưa (mm)] > 0 THÌ 1)\n"
        "÷ NULLIF(ĐẾM(NẾU [Loại quan sát] = “DU_BAO_NGAY” THÌ 1), 0)"
    )


@pytest.mark.parametrize(
    ("expression", "pseudo_code"),
    [
        ("AVG(CASE WHEN loai_quan_sat = 'DU_BAO_GIO' THEN nhiet_do_c END)",
         "TRUNG_BÌNH(NẾU [Loại quan sát] = “DU_BAO_GIO” THÌ [Nhiệt độ (°C)])"),
        ("SUM(CASE WHEN trang_thai = 'ok' THEN 1 ELSE 0 END)", "TỔNG(NẾU [trang_thai] = “ok” THÌ 1, CÒN LẠI 0)"),
        ("SUM(CASE WHEN nhiet_do_c IS NULL THEN 0 WHEN nhiet_do_c <> 2 THEN nhiet_do_c ELSE NULL END)",
         "TỔNG(NẾU [Nhiệt độ (°C)] TRỐNG THÌ 0, NẾU [Nhiệt độ (°C)] ≠ 2 THÌ [Nhiệt độ (°C)], CÒN LẠI RỖNG)"),
        ("CASE loai_quan_sat WHEN 'A' THEN 1 ELSE 0 END + 2", "(NẾU [Loại quan sát] = “A” THÌ 1, CÒN LẠI 0) + 2"),
        ("COUNT(*)", "ĐẾM(*)"),
        ("COUNT(DISTINCT thanh_pho_id)", "ĐẾM(KHÁC NHAU [Thành phố])"),
        ("SUM(tong_luong_mua_mm) FILTER (WHERE loai_quan_sat = 'X')",
         "TỔNG([Tổng lượng mưa (mm)]) CHỈ KHI [Loại quan sát] = “X”"),
        ("COALESCE(SUM(nhiet_do_c), 0)", "COALESCE(TỔNG([Nhiệt độ (°C)]), 0)"),
        ("SUM(nhiet_do_c::numeric) / NULLIF(COUNT(nhiet_do_c), 0)",
         "TỔNG(ĐỔI_KIỂU([Nhiệt độ (°C)], DECIMAL))\n÷ NULLIF(ĐẾM([Nhiệt độ (°C)]), 0)"),
        ("ROUND(AVG(nhiet_do_c), 1)", "ROUND(TRUNG_BÌNH([Nhiệt độ (°C)]), 1)"),
        ("MAX(DATE_TRUNC('day', ngay)) - MIN(EXTRACT(YEAR FROM ngay))",
         "LỚN_NHẤT(DATE_TRUNC(“DAY”, [Ngày])) - NHỎ_NHẤT(EXTRACT(YEAR FROM [Ngày]))"),
        ("SUM(nhiet_do_c) OVER (PARTITION BY thanh_pho_id ORDER BY ngay DESC)",
         "TỔNG([Nhiệt độ (°C)]) TRÊN (CHIA THEO [Thành phố] XẾP THEO [Ngày] GIẢM DẦN)"),
        ('AVG("nhiet_do_c") + MAX(t.tong_luong_mua_mm) + MIN(t.khong_co)',
         "TRUNG_BÌNH([Nhiệt độ (°C)]) + LỚN_NHẤT([Tổng lượng mưa (mm)]) + NHỎ_NHẤT([t.khong_co])"),
        ("COUNT(CASE WHEN nhiet_do_c BETWEEN 1 AND 2 AND ngay IS NOT NULL OR loai_quan_sat NOT IN ('A') THEN 1 END)",
         "ĐẾM(NẾU [Nhiệt độ (°C)] TỪ 1 ĐẾN 2 VÀ [Ngày] CÓ GIÁ TRỊ HOẶC [Loại quan sát] KHÔNG THUỘC (“A”) THÌ 1)"),
        ("COUNT(CASE WHEN NOT (loai_quan_sat = 'A' OR loai_quan_sat LIKE 'B%') THEN 1 END)",
         "ĐẾM(NẾU KHÔNG ([Loại quan sát] = “A” HOẶC [Loại quan sát] GIỐNG “B%”) THÌ 1)"),
    ],
)
def test_every_sql_form_reads_as_pseudo_code_with_dictionary_labels(expression, pseudo_code):
    assert metric_pseudo_code(expression, LABELS, "postgres") == pseudo_code


def test_an_expression_that_cannot_be_parsed_has_no_pseudo_code():
    assert metric_pseudo_code("SUM(nhiet_do_c) {% if filter_values('city') %}+ 0{% endif %}", LABELS) is None
    assert metric_pseudo_code("", LABELS) is None
    assert metric_pseudo_code(None, LABELS) is None
