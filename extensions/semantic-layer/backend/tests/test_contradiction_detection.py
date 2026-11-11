import pytest

from text_to_bi.superset_semantic_layer.modules.consistency.services.conditions import (
    Bound,
    ColumnDomain,
    Interval,
    bound_differences,
    region_contains,
    regions_overlap,
    rule_domains,
)
from text_to_bi.superset_semantic_layer.modules.consistency.services.detection import (
    MetricItem,
    RuleItem,
    TermItem,
    detect,
    semantic_candidates,
)
from text_to_bi.superset_semantic_layer.modules.consistency.services.thresholds import main_clause, stated_interval

RAIN = 96
TEMPERATURE = 92


def _condition(column_id, operator, value, value_type="number"):
    return {"field_ref": {"column_dictionary_id": column_id}, "operator": operator, "value_type": value_type,
            "value": value}


# The real "Ngày mưa lớn" rule: 50 mm up to, not including, 100 mm.
HEAVY_RAIN = [_condition(RAIN, "greater_than_or_equal", 50), _condition(RAIN, "less_than", 100)]


def _domain(*conditions):
    return rule_domains([_condition(RAIN, operator, value) for operator, value in conditions]).get(RAIN, ColumnDomain())


def _term(term_id, name, definition, **values):
    return TermItem(term_id, name, definition, f"term-{term_id}-{definition}", **values)


def _rule(rule_id, name, conditions, term_ids=(), dataset_id=12, examples=(), exceptions=(), **values):
    labels = {RAIN: "Tổng mưa (mm)", TEMPERATURE: "Nhiệt độ cao nhất (°C)"}
    names = {RAIN: "tong_mua_mm", TEMPERATURE: "nhiet_do_cao_nhat_c"}
    content = f"rule-{rule_id}-{conditions}-{examples}"
    return RuleItem(
        rule_id, name, dataset_id, content, tuple(conditions), tuple(exceptions), tuple(examples), frozenset(term_ids),
        labels, names, **values,
    )


def _kinds(findings):
    return [(finding.kind, [item.id for item in finding.items]) for finding in findings]


# Intervals and column domains.


def test_an_inclusive_and_an_exclusive_bound_on_one_number_share_nothing():
    assert not _domain(("greater_than_or_equal", 50)).overlaps(_domain(("less_than", 50)))
    assert _domain(("greater_than_or_equal", 50)).overlaps(_domain(("less_than_or_equal", 50)))
    assert _domain(("greater_than", 50)).describe("x") == "x > 50"
    assert _domain(("greater_than_or_equal", 50), ("less_than_or_equal", 50)).describe("x") == "x = 50"


def test_the_tighter_bound_wins_and_an_exclusive_bound_is_tighter_at_the_same_value():
    domain = _domain(("greater_than_or_equal", 30), ("greater_than", 50), ("greater_than_or_equal", 50))
    assert domain.interval == Interval(lower=Bound(50.0, False))
    assert _domain(("less_than", 100), ("less_than_or_equal", 100)).interval == Interval(upper=Bound(100.0, False))


def test_open_ranges_overlap_and_nest():
    above_30, above_50 = _domain(("greater_than_or_equal", 30)), _domain(("greater_than_or_equal", 50))
    assert above_30.overlaps(above_50) and above_30.contains(above_50) and not above_50.contains(above_30)
    below_20 = _domain(("less_than", 20))
    assert not below_20.overlaps(above_30)
    assert ColumnDomain().contains(above_30) and not above_30.contains(ColumnDomain())


def test_conditions_that_cannot_hold_together_leave_an_empty_domain():
    assert _domain(("greater_than_or_equal", 50), ("less_than", 30)).is_empty()
    assert _domain(("greater_than", 50), ("less_than_or_equal", 50)).is_empty()
    assert _domain(("in", [1, 2]), ("greater_than", 5)).is_empty()
    assert _domain(("equals", 50), ("not_equals", 50)).is_empty()
    assert not _domain(("greater_than_or_equal", 50), ("less_than", 50.5)).is_empty()


def test_in_lists_keep_only_the_members_both_sides_allow():
    cities = rule_domains([_condition(7, "in", ["Hà Nội", "Đà Nẵng"], "array")])[7]
    assert cities.overlaps(rule_domains([_condition(7, "equals", "Đà Nẵng", "string")])[7])
    assert not cities.overlaps(rule_domains([_condition(7, "not_in", ["Hà Nội", "Đà Nẵng"], "array")])[7])
    assert not cities.overlaps(rule_domains([_condition(7, "in", ["Huế"], "array")])[7])
    assert cities.describe("Thành phố") == "Thành phố thuộc {“Hà Nội”, “Đà Nẵng”}"
    # A list of numbers is filtered by a bound, and 50 equals 50.0 while true does not equal 1.
    numbers = rule_domains([_condition(RAIN, "in", [10, 50, 80], "array"), _condition(RAIN, "greater_than", 20)])
    assert numbers[RAIN].describe("x") == "x thuộc {50, 80}"
    assert _domain(("equals", 50)).overlaps(_domain(("in", [50.0])))
    assert not rule_domains([_condition(1, "equals", True, "boolean")])[1].overlaps(
        rule_domains([_condition(1, "equals", 1)])[1]
    )


def test_null_checks_and_text_matching():
    null_checks = [_condition(1, "is_null", None, "null"), _condition(1, "is_not_null", None, "null")]
    assert rule_domains(null_checks)[1].is_empty()
    # Text matching is not reasoned about, so it never makes a contradiction on its own.
    assert rule_domains([_condition(1, "contains", "mưa", "string")]) == {}


def test_a_region_spans_every_column_of_both_rules():
    first = rule_domains([_condition(RAIN, "greater_than_or_equal", 50), _condition(TEMPERATURE, "greater_than", 30)])
    second = rule_domains([_condition(RAIN, "greater_than_or_equal", 60)])
    assert regions_overlap(first, second)
    assert region_contains(rule_domains([_condition(RAIN, "greater_than_or_equal", 50)]), first)
    assert not region_contains(first, second)


def test_only_the_bounds_a_text_states_are_compared():
    actual = Interval(Bound(50.0, True), Bound(100.0, False))
    assert bound_differences(Interval(lower=Bound(50.0, True)), actual) == []
    assert bound_differences(Interval(lower=Bound(50.0, False)), actual) == ["ngưỡng dưới > 50 so với ≥ 50"]
    assert bound_differences(Interval(upper=Bound(80.0, True)), actual) == ["ngưỡng trên ≤ 80 so với < 100"]
    assert bound_differences(Interval(upper=Bound(80.0, True)), Interval()) == ["ngưỡng trên ≤ 80 so với không có"]


# Thresholds stated in Vietnamese prose.


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Ngày có tổng lượng mưa trên 50 mm; trên 100 mm là mưa rất to.", "x > 50"),
        ("Ngày có nhiệt độ trung bình từ 15°C trở xuống; từ 13°C trở xuống là rét hại.", "x ≤ 15"),
        ("Tốc độ gió hoặc gió giật tối đa từ 39 km/h trở lên (từ cấp 6).", "x ≥ 39"),
        ("Thời tiết có độ ẩm trung bình từ 90% trở lên, không khí ẩm ướt.", "x ≥ 90"),
        ("Ngày có lượng mưa lớn hơn 0 mm; mỗi thành phố, mỗi ngày đếm một lần.", "x > 0"),
        ("Lượng mưa từ 50 đến 100 mm", "x ≥ 50 và ≤ 100"),
        ("không quá 1,5 mm và ít nhất 0.5 mm", "x ≥ 0.5 và ≤ 1.5"),
        ("Nhiệt độ ≥ 37 và < 40", "x ≥ 37 và < 40"),
        ("Dưới 5°C", "x < 5"),
    ],
)
def test_a_threshold_is_read_from_the_first_clause(text, expected):
    assert ColumnDomain(stated_interval(text)).describe("x") == expected


@pytest.mark.parametrize(
    "text",
    [
        "Thời tiết nóng bức, khó chịu cho con người",
        "Tháng nào có trên 10 ngày mưa lớn?",
        "Số giờ có nắng trong ngày.",
        "trên 50 và dưới 30",
        "",
        None,
    ],
)
def test_no_threshold_is_read_from_counts_prose_or_impossible_ranges(text):
    assert stated_interval(text) is None


def test_the_main_clause_keeps_decimals_whole():
    assert main_clause("Mưa trên 1.5 mm. Ghi chú khác") == "Mưa trên 1.5 mm"


# Rule-based checks.


def test_a_word_claimed_by_two_terms_clashes_unless_they_share_a_group():
    terms = [
        _term(1, "Mưa lớn", "Ngày có mưa trên 50 mm.", synonyms=("mưa to",)),
        _term(2, "Mưa rất to", "Ngày có mưa trên 100 mm.", synonyms=("Mưa  To",)),
        _term(3, "Mưa to", "Mưa nặng hạt."),
    ]
    findings = detect(terms, [])
    assert _kinds(findings) == [("term_name_clash", [1, 2]), ("term_name_clash", [1, 3]), ("term_name_clash", [2, 3])]
    assert "“mưa to” là từ đồng nghĩa của “Mưa lớn” và là tên của “Mưa to”." in findings[1].evidence
    grouped = [_term(1, "Mưa lớn", "x", synonyms=("mưa to",), group_id=4), _term(3, "Mưa to", "y", group_id=4)]
    assert detect(grouped, []) == []


def test_a_rule_whose_conditions_exclude_each_other_never_applies():
    rule = _rule(1, "Mưa vô lý", [_condition(RAIN, "greater_than_or_equal", 50), _condition(RAIN, "less_than", 30)])
    [finding] = detect([], [rule])
    assert finding.kind == "rule_conditions_empty" and [item.id for item in finding.items] == [1]
    assert finding.evidence == ("Tổng mưa (mm) ≥ 50 VÀ Tổng mưa (mm) < 30",)


def test_two_rules_defining_one_term_with_different_thresholds_contradict():
    term = _term(6, "Mưa lớn", "Mưa nặng hạt.")
    first = _rule(1, "Mưa lớn A", [_condition(RAIN, "greater_than_or_equal", 50)], [6])
    second = _rule(2, "Mưa lớn B", [_condition(RAIN, "greater_than_or_equal", 30)], [6])
    [finding] = detect([term], [first, second])
    assert finding.kind == "rule_rule_same_term"
    assert finding.evidence == ("Rule “Mưa lớn A”: Tổng mưa (mm) ≥ 50", "Rule “Mưa lớn B”: Tổng mưa (mm) ≥ 30")
    assert "một rule nằm trọn trong rule kia" in finding.explanation
    disjoint = _rule(3, "Mưa lớn C", [_condition(RAIN, "less_than", 30)], [6])
    assert "không có dòng nào thỏa cả hai" in detect([term], [first, disjoint])[0].explanation
    # The same conditions twice, or rules on other datasets, are not contradictions.
    assert detect([term], [first, _rule(4, "Bản sao", first.conditions, [6])]) == []
    assert detect([term], [first, _rule(5, "Khác dataset", second.conditions, [6], dataset_id=13)]) == []


def test_rules_of_different_terms_contradict_when_their_rows_partly_overlap_or_coincide():
    terms = [_term(6, "Mưa lớn", "a"), _term(7, "Mưa rất to", "b")]
    heavy = _rule(1, "Mưa lớn", HEAVY_RAIN, [6])
    partly = _rule(2, "Mưa rất to", [_condition(RAIN, "greater_than_or_equal", 80)], [7])
    [finding] = detect(terms, [heavy, partly])
    assert finding.kind == "rule_rule_overlap" and "“Mưa lớn” và “Mưa rất to”" in finding.explanation
    # Touching at an excluded bound, nested grades, and rules on different columns do not overlap.
    after = _rule(3, "Mưa rất to", [_condition(RAIN, "greater_than_or_equal", 100)], [7])
    nested = _rule(4, "Mưa rất to", [_condition(RAIN, "greater_than_or_equal", 60)], [7])
    other_column = _rule(5, "Nóng", [_condition(TEMPERATURE, "greater_than_or_equal", 35)], [7])
    assert detect(terms, [heavy, after]) == []
    assert detect(terms, [_rule(1, "Mưa lớn", [_condition(RAIN, "greater_than_or_equal", 50)], [6]), nested]) == []
    assert detect(terms, [heavy, other_column]) == []
    same = _rule(6, "Mưa to", heavy.conditions, [7])
    assert "giống hệt nhau" in detect(terms, [heavy, same])[0].explanation


def test_a_rule_threshold_other_than_its_term_definition_contradicts_it():
    term = _term(6, "Mưa lớn", "Ngày có tổng lượng mưa trên 50 mm; trên 100 mm là mưa rất to.")
    rule = _rule(2, "Ngày mưa lớn", HEAVY_RAIN, [6])
    [finding] = detect([term], [rule])
    assert finding.kind == "rule_term_threshold" and [item.type for item in finding.items] == ["rule", "term"]
    assert finding.evidence == (
        "Thuật ngữ “Mưa lớn”: “Ngày có tổng lượng mưa trên 50 mm” → Tổng mưa (mm) > 50",
        "Rule “Ngày mưa lớn”: Tổng mưa (mm) ≥ 50 và < 100",
    )
    assert "ngưỡng dưới > 50 so với ≥ 50" in finding.explanation
    agreeing = _rule(2, "Ngày mưa lớn", [_condition(RAIN, "greater_than", 50), _condition(RAIN, "less_than", 100)], [6])
    assert detect([term], [agreeing]) == []
    # A term stating no threshold, or a rule bounding two columns the term does not link, is not compared.
    assert detect([_term(6, "Mưa lớn", "Mưa nặng hạt.")], [rule]) == []
    two_columns = _rule(2, "x", [*rule.conditions, _condition(TEMPERATURE, "greater_than", 20)], [6])
    assert detect([term], [two_columns]) == []
    linked = _term(6, "Mưa lớn", term.definition, columns=frozenset({(12, "tong_mua_mm")}))
    assert _kinds(detect([linked], [two_columns])) == [("rule_term_threshold", [2, 6])]


def test_an_example_stating_another_threshold_contradicts_its_rule():
    examples = (
        {"question": "Tháng này có mấy ngày nắng nóng?", "intent": "Đếm số ngày có nhiệt độ cao nhất từ 35°C trở lên"},
    )
    rule = _rule(1, "Ngày nắng nóng", [_condition(TEMPERATURE, "greater_than_or_equal", 37)], examples=examples)
    [finding] = detect([], [rule])
    assert finding.kind == "rule_example_threshold"
    assert finding.evidence[-1] == "Điều kiện của rule: Nhiệt độ cao nhất (°C) ≥ 37"
    fixed = ({"question": "Tháng này có mấy ngày nắng nóng?", "intent": "Đếm số ngày từ 37°C trở lên"},)
    assert detect([], [_rule(1, "Ngày nắng nóng", rule.conditions, examples=fixed)]) == []


def test_the_fingerprint_follows_the_content_of_both_items():
    term = _term(6, "Mưa lớn", "Ngày có tổng lượng mưa trên 50 mm.")
    rule = _rule(2, "Ngày mưa lớn", [_condition(RAIN, "greater_than_or_equal", 50)], [6])
    [first] = detect([term], [rule])
    [again] = detect([term], [rule])
    [edited] = detect([_term(6, "Mưa lớn", "Ngày có tổng lượng mưa trên 40 mm.")], [rule])
    assert first.fingerprint == again.fingerprint
    assert first.pair_key == edited.pair_key == "rule_term_threshold:rule:2|term:6"
    assert edited.fingerprint != first.fingerprint


# Candidate pairs for the AI model.


def test_only_related_pairs_are_sent_to_the_model_and_flagged_pairs_are_not():
    rain = _term(5, "Lượng mưa", "Tổng lượng nước mưa.", columns=frozenset({(12, "tong_luong_mua_mm")}),
                 metric_ids=frozenset({20}))
    heavy = _term(6, "Mưa lớn", "Ngày có tổng lượng mưa trên 50 mm.", columns=frozenset({(12, "tong_luong_mua_mm")}))
    sunshine = _term(12, "Giờ nắng", "Số giờ có nắng trong ngày.")
    metric = MetricItem(20, 12, "Tổng lượng mưa", "TỔNG([Tổng mưa (mm)])", "metric-20")
    flagged_rule = _rule(2, "Ngày mưa lớn", [_condition(RAIN, "greater_than_or_equal", 50)], [6])
    calm_rule = _rule(3, "Ngày nắng", [_condition(TEMPERATURE, "greater_than", 30)], [12])
    findings = detect([rain, heavy, sunshine], [flagged_rule, calm_rule])
    candidates = semantic_candidates([rain, heavy, sunshine], [flagged_rule, calm_rule], [metric], findings)
    assert [(candidate.kind, [item.id for item in candidate.items]) for candidate in candidates] == [
        ("term_term_meaning", [5, 6]),
        ("term_metric_meaning", [5, 20]),
        ("rule_term_meaning", [3, 12]),
    ]
    assert candidates[1].texts == ("Thuật ngữ “Lượng mưa”. Định nghĩa: Tổng lượng nước mưa.",
                                   "Metric “Tổng lượng mưa”. Công thức: TỔNG([Tổng mưa (mm)])")
    assert candidates[2].texts[0].startswith("Rule “Ngày nắng”. Điều kiện: Nhiệt độ cao nhất (°C) > 30.")


def test_rules_sharing_a_term_or_a_condition_column_are_sent_as_a_pair():
    first = _rule(1, "A", [_condition(RAIN, "greater_than_or_equal", 50)], exceptions=({"when": "x", "outcome": "y"},))
    example = {"question": "q", "intent": "i"}
    second = _rule(2, "B", [_condition(RAIN, "greater_than_or_equal", 50)], examples=(example,))
    third = _rule(3, "C", [_condition(TEMPERATURE, "greater_than_or_equal", 50)])
    candidates = semantic_candidates([], [first, second, third], [], [])
    assert [(candidate.kind, [item.id for item in candidate.items]) for candidate in candidates] == [
        ("rule_rule_meaning", [1, 2])
    ]
    assert "Ngoại lệ: khi x thì y." in candidates[0].texts[0] and "Câu hỏi mẫu: “q” → i." in candidates[0].texts[1]
