import ast
import importlib
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from catalog_source import api_class, api_methods, compile_into
from sqlalchemy.exc import IntegrityError

from text_to_bi.superset_semantic_layer.core.exceptions import AdminRequiredError
from text_to_bi.superset_semantic_layer.modules.consistency.exceptions import (
    ContradictionCheckConflictError,
    ContradictionNotFoundError,
    ContradictionValidationError,
)
from text_to_bi.superset_semantic_layer.modules.consistency.services import judgement
from text_to_bi.superset_semantic_layer.modules.consistency.services.detection import Candidate, ItemReference
from text_to_bi.superset_semantic_layer.modules.consistency.services.judgement import (
    PairVerdicts,
    SemanticOutcome,
    Verdict,
    judge_candidates,
    parse_verdicts,
    semantic_findings,
)
from text_to_bi.superset_semantic_layer.modules.consistency.services.lifecycle import (
    dismissal_reason,
    found_by,
    reconcile,
)

PACKAGE = "text_to_bi.superset_semantic_layer"
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


def _candidate(number, kind="term_term_meaning"):
    items = (ItemReference("term", number, f"T{number}"), ItemReference("term", number + 100, f"T{number + 100}"))
    return Candidate(kind, items, f"fingerprint-{number}", (f"mục {number}", f"mục {number + 100}"))


# The AI model's verdicts.


def test_verdicts_are_read_by_position_and_malformed_answers_are_left_to_retry():
    candidates = [_candidate(1), _candidate(2), _candidate(3)]
    raw = {
        "verdicts": [
            {"pair_id": "0", "contradiction": True, "explanation": "  Ngưỡng   trái nhau. "},
            {"pair_id": "1", "contradiction": True, "explanation": ""},
            {"pair_id": "7", "contradiction": True, "explanation": "không có cặp này"},
            {"pair_id": "x", "contradiction": False},
        ]
    }
    assert parse_verdicts(raw, candidates) == {
        "fingerprint-1": Verdict(True, "Ngưỡng trái nhau."),
        "fingerprint-2": Verdict(True, judgement.FALLBACK_EXPLANATION),
    }
    model_answer = PairVerdicts.model_validate({"verdicts": [{"pair_id": "2", "contradiction": False}]})
    assert parse_verdicts(model_answer, candidates) == {"fingerprint-3": Verdict(False, "")}
    assert parse_verdicts({"verdicts": "không phải danh sách"}, candidates) == {}
    assert parse_verdicts(None, candidates) == {}


def test_the_request_names_each_pair_by_position_with_its_question():
    request = judgement.judge_request([_candidate(1, "rule_term_meaning")])
    assert '"pair_id": "0"' in request and judgement.KIND_QUESTIONS["rule_term_meaning"] in request
    assert '"muc_1": "mục 1"' in request


def test_cached_pairs_are_not_judged_again_and_new_ones_go_in_batches():
    candidates = [_candidate(number) for number in range(8)]
    asked = []

    def judge(batch):
        asked.append([candidate.fingerprint for candidate in batch])
        return {candidate.fingerprint: Verdict(candidate.fingerprint.endswith("3"), "x") for candidate in batch}

    cached = {"fingerprint-0": Verdict(False, ""), "fingerprint-1": Verdict(True, "đã biết")}
    verdicts, fresh, outcome = judge_candidates(candidates, cached, judge)
    assert sorted(fingerprint for batch in asked for fingerprint in batch) == [f"fingerprint-{n}" for n in range(2, 8)]
    assert max(len(batch) for batch in asked) <= judgement.PAIRS_PER_CALL
    assert set(fresh) == {f"fingerprint-{n}" for n in range(2, 8)} and len(verdicts) == 8
    assert outcome == SemanticOutcome("checked")
    findings = semantic_findings(candidates, verdicts)
    assert [(finding.fingerprint, finding.explanation) for finding in findings] == [
        ("fingerprint-1", "đã biết"), ("fingerprint-3", "x")
    ]
    assert findings[0].evidence == ("mục 1", "mục 101")
    asked.clear()
    assert judge_candidates(candidates, verdicts, judge)[2] == SemanticOutcome("checked") and asked == []


def test_without_a_key_nothing_is_asked_and_the_pairs_stay_unchecked(monkeypatch):
    monkeypatch.setattr(judgement.settings, "OPENROUTER_API_KEY", "")
    assert judgement.semantic_judge() is None
    cached = {"fingerprint-1": Verdict(True, "a")}
    verdicts, fresh, outcome = judge_candidates([_candidate(1), _candidate(2)], cached, None)
    assert verdicts == {"fingerprint-1": Verdict(True, "a")} and fresh == {}
    assert outcome == SemanticOutcome("unavailable", 1, judgement.UNAVAILABLE_MESSAGE)
    monkeypatch.setattr(judgement.settings, "OPENROUTER_API_KEY", "khóa-thử")
    assert judgement.semantic_judge() is judgement.model_judge


def test_a_deferred_check_asks_nothing_and_leaves_the_pairs_for_the_ai_step():
    asked = []

    def judge(batch):
        asked.append(batch)
        return {}

    cached = {"fingerprint-1": Verdict(True, "a")}
    verdicts, fresh, outcome = judge_candidates([_candidate(1), _candidate(2)], cached, judge, defer=True)
    assert verdicts == cached and fresh == {} and asked == []
    assert outcome == SemanticOutcome("deferred", 1)
    # Without a key there is no AI step to wait for.
    assert judge_candidates([_candidate(2)], {}, None, defer=True)[2].status == "unavailable"
    assert judge_candidates([_candidate(1)], cached, judge, defer=True)[2] == SemanticOutcome("checked")


def test_the_chat_model_gives_up_before_the_worker_timeout(monkeypatch):
    chat_models = importlib.import_module(f"{PACKAGE}.modules.data_dictionary.autofill.chat_models")
    monkeypatch.setattr(chat_models.settings, "OPENROUTER_API_KEY", "khóa-thử")
    chat_models.get_chat_model.cache_clear()
    try:
        model = chat_models.get_chat_model()
    finally:
        chat_models.get_chat_model.cache_clear()
    assert model.request_timeout == chat_models.CHAT_MODEL_TIMEOUT_SECONDS and model.max_retries == 1
    assert chat_models.CHAT_MODEL_TIMEOUT_SECONDS * (1 + model.max_retries) < 120


def test_a_failing_model_leaves_the_pairs_for_the_next_check():
    def judge(batch):
        raise TimeoutError("OpenRouter")

    verdicts, fresh, outcome = judge_candidates([_candidate(1)], {}, judge)
    assert verdicts == {} and fresh == {}
    assert outcome == SemanticOutcome("failed", 1, judgement.FAILED_MESSAGE)


def test_a_large_glossary_is_judged_over_several_checks(monkeypatch):
    monkeypatch.setattr(judgement, "PAIRS_PER_CHECK", 3)
    candidates = [_candidate(number) for number in range(5)]
    def judge(batch):
        return {candidate.fingerprint: Verdict(False, "") for candidate in batch}

    _, fresh, outcome = judge_candidates(candidates, {}, judge)
    assert len(fresh) == 3 and outcome.status == "pending" and outcome.unchecked == 2
    assert "Còn 2 cặp" in outcome.message


# The review lifecycle.


class _Row:
    def __init__(self, **values):
        self.id = None
        self.dismiss_reason = self.dismissed_by = self.dismissed_at = None
        self.__dict__.update(values)


def _finding(fingerprint="fingerprint-a", kind="rule_term_threshold"):
    items = (ItemReference("rule", 2, "Ngày mưa lớn"), ItemReference("term", 6, "Mưa lớn"))
    return judgement.Finding(kind, items, fingerprint, ("bằng chứng",), "giải thích")


def test_a_dismissal_holds_while_the_content_is_unchanged_and_is_reset_when_it_changes():
    [row], deleted = reconcile([], [_finding()], lambda values: _Row(**values), NOW)
    assert deleted == [] and row.status == "open" and row.pair_key == "rule_term_threshold:rule:2|term:6"
    assert row.items == [
        {"type": "rule", "id": 2, "name": "Ngày mưa lớn"}, {"type": "term", "id": 6, "name": "Mưa lớn"}
    ]
    row.status, row.dismiss_reason, row.dismissed_by, row.dismissed_at = "dismissed", "Chấp nhận", 3, NOW
    assert reconcile([row], [_finding()], _Row, NOW) == ([], [])
    assert row.status == "dismissed" and row.dismiss_reason == "Chấp nhận"
    later = datetime(2026, 11, 12, tzinfo=timezone.utc)
    reconcile([row], [_finding("fingerprint-b")], _Row, later)
    assert (row.status, row.dismiss_reason, row.dismissed_by, row.dismissed_at) == ("open", None, None, None)
    assert row.fingerprint == "fingerprint-b" and row.detected_at == later
    assert reconcile([row], [], _Row, later) == ([], [row])


@pytest.mark.parametrize("payload", [None, {}, {"reason": "   "}, {"reason": 5}, {"reason": "x" * 513}])
def test_a_dismissal_needs_a_bounded_reason(payload):
    with pytest.raises(ContradictionValidationError):
        dismissal_reason(payload)


def test_a_dismissal_reason_is_trimmed_and_kinds_say_who_found_them():
    assert dismissal_reason({"reason": "  Hai mức   khác nhau "}) == "Hai mức khác nhau"
    assert found_by("term_term_meaning") == "ai" and found_by("rule_term_threshold") == "rule"


# The service on in-memory repositories.


class _Store:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def add(self, row, flush=True):
        row.id = max((item.id for item in self.rows), default=0) + 1
        self.rows.append(row)
        return row

    def delete(self, row):
        self.rows.remove(row)

    def flush(self):
        pass

    def get(self, row_id):
        return next((row for row in self.rows if row.id == row_id), None)

    def by_id(self):
        return sorted(self.rows, key=lambda row: row.id)

    def for_fingerprints(self, fingerprints):
        return [row for row in self.rows if row.fingerprint in fingerprints]

    def delete_except(self, fingerprints):
        self.rows = [row for row in self.rows if row.fingerprint in fingerprints]


def _condition(column_id, operator, value):
    return {"field_ref": {"column_dictionary_id": column_id}, "operator": operator, "value_type": "number",
            "value": value}


@pytest.fixture
def world(monkeypatch):
    """The service with the glossary, expert rules, data dictionary and Superset faked in memory."""
    terms = {
        5: SimpleNamespace(id=5, canonical_name="Lượng mưa", group_id=None),
        6: SimpleNamespace(id=6, canonical_name="Mưa lớn", group_id=None),
    }
    term_revisions = {
        5: SimpleNamespace(id=50, status="approved", definition="Tổng lượng nước mưa.", synonyms=[], content_hash="t5"),
        6: SimpleNamespace(
            id=60, status="approved", definition="Ngày có tổng lượng mưa trên 50 mm.", synonyms=[], content_hash="t6"
        ),
    }
    term_links = {
        50: [SimpleNamespace(kind="column", dataset_id=12, column_name="tong_mua_mm", metric_id=None)],
        60: [
            SimpleNamespace(kind="column", dataset_id=12, column_name="tong_mua_mm", metric_id=None),
            SimpleNamespace(kind="metric", dataset_id=12, column_name=None, metric_id=20),
        ],
    }
    rule_revision = SimpleNamespace(
        id=200, rule_id=2, status="approved", name="Ngày mưa lớn", content_hash="r2", exceptions=[], examples=[],
        conditions=[_condition(96, "greater_than_or_equal", 50), _condition(96, "less_than", 100)],
    )
    rule_links = {200: [SimpleNamespace(kind="glossary", target_id=6), SimpleNamespace(kind="dataset", target_id=12)]}
    column = SimpleNamespace(column_name="tong_mua_mm", display_name="Tổng mưa (mm)")
    metric = SimpleNamespace(
        id=20, metric_name="tong_luong_mua", verbose_name="Tổng lượng mưa", expression="SUM(tong_mua_mm)"
    )
    contradictions, judgements = _Store(), _Store()

    def module(name, **values):
        fake = types.ModuleType(f"{PACKAGE}.{name}")
        fake.__dict__.update(values)
        monkeypatch.setitem(sys.modules, fake.__name__, fake)

    module(
        "modules.glossary.dependencies",
        glossary_term_repository=lambda: SimpleNamespace(by_canonical_name=lambda: list(terms.values())),
        glossary_term_revision_repository=lambda: SimpleNamespace(current_for=term_revisions.get),
        glossary_term_link_repository=lambda: SimpleNamespace(for_revision=lambda revision_id: term_links[revision_id]),
    )
    module(
        "modules.expert_rules.dependencies",
        expert_rule_repository=lambda: SimpleNamespace(get=lambda rule_id: SimpleNamespace(id=rule_id, dataset_id=12)),
        expert_rule_revision_repository=lambda: SimpleNamespace(current=lambda: [rule_revision]),
        expert_rule_link_repository=lambda: SimpleNamespace(for_revision=lambda revision_id: rule_links[revision_id]),
    )
    module(
        "modules.data_dictionary.dependencies",
        column_dictionary_repository=lambda: SimpleNamespace(
            get=lambda column_id: column if column_id == 96 else None, list_for_dataset=lambda dataset_id: [column]
        ),
    )
    module("modules.superset.services.datasets", get_dataset=lambda dataset_id: SimpleNamespace(metrics=[metric]))
    module(
        "modules.consistency.dependencies",
        contradiction_repository=lambda: contradictions,
        contradiction_judgement_repository=lambda: judgements,
    )
    module("modules.consistency.models", Contradiction=_Row, ContradictionJudgement=_Row)
    monkeypatch.delitem(sys.modules, f"{PACKAGE}.modules.consistency.services.review", raising=False)
    review = importlib.import_module(f"{PACKAGE}.modules.consistency.services.review")
    return SimpleNamespace(
        review=review, term_revisions=term_revisions, contradictions=contradictions, judgements=judgements,
    )


def _stub_judge(asked):
    def judge(batch):
        asked.extend((candidate.kind, [item.id for item in candidate.items]) for candidate in batch)
        return {
            candidate.fingerprint: Verdict(candidate.kind == "term_term_meaning", "Hai định nghĩa trái nhau.")
            for candidate in batch
        }

    return judge


def test_a_check_stores_rule_and_ai_findings_and_remembers_the_verdicts(world):
    asked = []
    outcome = world.review.refresh_contradictions(_stub_judge(asked))
    assert outcome == SemanticOutcome("checked")
    # The rule and term already contradict by their thresholds, so that pair is not sent to the model.
    assert asked == [("term_term_meaning", [5, 6]), ("term_metric_meaning", [6, 20])]
    rows = world.review.contradictions_for_review()
    assert [(row.kind, row.status) for row in rows] == [("rule_term_threshold", "open"), ("term_term_meaning", "open")]
    assert len(world.judgements.rows) == 2
    asked.clear()
    world.review.refresh_contradictions(_stub_judge(asked))
    assert asked == [] and len(world.contradictions.rows) == 2


def test_a_dismissed_contradiction_comes_back_only_when_an_item_changes(world):
    world.review.refresh_contradictions(_stub_judge([]))
    threshold = next(row for row in world.contradictions.rows if row.kind == "rule_term_threshold")
    world.review.mark_contradiction_dismissed(threshold.id, "Chấp nhận ranh giới 50 mm", 3)
    assert threshold.status == "dismissed" and threshold.dismissed_by == 3
    world.review.refresh_contradictions(_stub_judge([]))
    assert threshold.status == "dismissed"

    world.term_revisions[6] = SimpleNamespace(
        id=60, status="draft", definition="Ngày có tổng lượng mưa trên 40 mm.", synonyms=[], content_hash="t6-2"
    )
    asked = []
    world.review.refresh_contradictions(_stub_judge(asked))
    assert threshold.status == "open" and threshold.dismiss_reason is None
    assert "Tổng mưa (mm) > 40" in threshold.evidence[0]
    # Only the pairs holding the edited term are judged again.
    assert asked == [("term_term_meaning", [5, 6]), ("term_metric_meaning", [6, 20])]

    agreeing = "Ngày có tổng lượng mưa từ 50 mm trở lên."
    world.term_revisions[6] = SimpleNamespace(
        id=60, status="approved", definition=agreeing, synonyms=[], content_hash="t6-3"
    )
    world.review.refresh_contradictions(_stub_judge([]))
    assert [row.kind for row in world.contradictions.rows] == ["term_term_meaning"]


def test_revoked_content_is_not_checked_and_an_unknown_contradiction_is_404(world):
    world.term_revisions[6] = SimpleNamespace(
        id=60, status="revoked", definition="Ngày có tổng lượng mưa trên 50 mm.", synonyms=[], content_hash="t6"
    )
    world.review.refresh_contradictions(_stub_judge([]))
    assert world.contradictions.rows == []
    with pytest.raises(ContradictionNotFoundError):
        world.review.mark_contradiction_dismissed(99, "x", 3)


def test_without_a_key_the_rule_based_findings_are_still_stored(world):
    outcome = world.review.refresh_contradictions(None)
    assert outcome.status == "unavailable" and outcome.unchecked == 2
    assert [row.kind for row in world.contradictions.rows] == ["rule_term_threshold"]


def test_a_rule_only_check_stores_the_rule_findings_and_the_ai_step_adds_its_own(world):
    asked = []
    outcome = world.review.refresh_contradictions(_stub_judge(asked), defer_model=True)
    assert outcome == SemanticOutcome("deferred", 2) and asked == []
    assert [row.kind for row in world.contradictions.rows] == ["rule_term_threshold"]
    assert world.review.refresh_contradictions(_stub_judge(asked)) == SemanticOutcome("checked")
    assert sorted(row.kind for row in world.contradictions.rows) == ["rule_term_threshold", "term_term_meaning"]
    # Once judged, the AI findings come back from the cache in the rule-only step too.
    assert world.review.refresh_contradictions(_stub_judge(asked), defer_model=True) == SemanticOutcome("checked")
    assert len(world.contradictions.rows) == 2


def test_a_failing_model_keeps_earlier_verdicts(world):
    world.review.refresh_contradictions(_stub_judge([]))

    def failing(batch):
        raise RuntimeError("OpenRouter")

    world.term_revisions[5] = SimpleNamespace(
        id=50, status="approved", definition="Lượng nước mưa.", synonyms=[], content_hash="t5-2"
    )
    outcome = world.review.refresh_contradictions(failing)
    assert outcome.status == "failed"
    # The verdict on the unchanged term and metric stays cached; the edited pair waits for the next check.
    assert len(world.judgements.rows) == 2
    assert [row.kind for row in world.contradictions.rows] == ["rule_term_threshold"]


# The routes.

ROUTES = {
    "check_contradictions": "/contradictions/check",
    "dismiss_contradiction": "/contradictions/<int:contradiction_id>/dismiss",
}


def _decorator_names(method):
    names = []
    for decorator in method.decorator_list:
        node = decorator.func if isinstance(decorator, ast.Call) else decorator
        names.append(node.id if isinstance(node, ast.Name) else node.attr)
    return names


def test_contradiction_routes_are_admin_writes_in_the_handbook_order():
    methods = api_methods()
    for name, route in ROUTES.items():
        method = methods[name]
        assert _decorator_names(method) == [
            "expose", "protect", "safe", "permission_name", "csrf_protected", "rollback_on_error", "handle_errors"
        ]
        assert ast.unparse(method.decorator_list[0]) == f"expose('{route}', methods=('POST',))"
        assert ast.unparse(method.body[1].value) == "require_admin()"
        assert ast.unparse(method).count("db.session.commit()") == 1


class _ResponseAPI:
    def response(self, status, **payload):
        return status, payload


def _api(*, admin=True, body=None, refresh=None, dismiss=None):
    commits = []

    def require_admin():
        if not admin:
            raise AdminRequiredError()

    row = _Row(
        id=4, kind="rule_term_threshold", status="open", items=[], evidence=["a"], explanation="b", detected_at=NOW
    )
    namespace = {
        "RestApi": _ResponseAPI,
        "require_admin": require_admin,
        "ensure_dictionary_tables": lambda: None,
        "request": SimpleNamespace(get_json=lambda silent=True: body),
        "current_user": SimpleNamespace(id=3),
        "db": SimpleNamespace(session=SimpleNamespace(commit=lambda: commits.append(True), rollback=lambda: None)),
        "IntegrityError": IntegrityError,
        "semantic_judge": lambda: "judge",
        "refresh_contradictions": refresh or (lambda judge, defer_model=False: SemanticOutcome("checked")),
        "contradictions_for_review": lambda: [row],
        "mark_contradiction_dismissed": dismiss or (lambda contradiction_id, reason, actor_id: row),
        "dismissal_reason": dismissal_reason,
        "found_by": found_by,
        "user_names": lambda: lambda user_id: {3: "Bao Reviewer"}.get(user_id),
    }
    compile_into(namespace, api_class({"check_contradictions", "dismiss_contradiction", "_contradiction"}))
    return namespace["SemanticLayerAPI"](), commits


def test_a_check_answers_the_contradictions_and_the_ai_outcome_after_one_commit():
    judges = []

    def refresh(judge, defer_model=False):
        judges.append((judge, defer_model))
        return SemanticOutcome("unavailable", 2, "Chưa cấu hình")

    api, commits = _api(refresh=refresh)
    status, payload = api.check_contradictions()
    assert status == 200 and commits == [True] and judges == [("judge", False)]
    assert payload["semantic"] == {"status": "unavailable", "unchecked": 2, "message": "Chưa cấu hình"}
    [entry] = payload["contradictions"]
    assert entry["found_by"] == "rule" and entry["detected_at"] == "2026-11-11T00:00:00+00:00"


def test_a_rules_only_check_leaves_the_model_for_the_next_request():
    judges = []

    def refresh(judge, defer_model=False):
        judges.append(defer_model)
        return SemanticOutcome("deferred", 3)

    api, commits = _api(body={"rules_only": True}, refresh=refresh)
    status, payload = api.check_contradictions()
    assert status == 200 and commits == [True] and judges == [True]
    assert payload["semantic"] == {"status": "deferred", "unchecked": 3, "message": None}
    api, commits = _api(body={"rules_only": "yes"}, refresh=refresh)
    api.check_contradictions()
    assert judges == [True, False]


def test_a_concurrent_check_is_a_conflict_and_saves_nothing():
    def refresh(judge, defer_model=False):
        raise IntegrityError("insert", {}, Exception("duplicate pair_key"))

    api, commits = _api(refresh=refresh)
    assert api.check_contradictions() == (409, {"message": ContradictionCheckConflictError.message})
    assert commits == []


def test_a_dismissal_records_the_reason_and_the_administrator():
    received = []

    def dismiss(contradiction_id, reason, actor_id):
        received.append((contradiction_id, reason, actor_id))
        return _Row(
            id=contradiction_id, kind="term_term_meaning", status="dismissed", items=[], evidence=[], explanation="x",
            detected_at=NOW, dismiss_reason=reason, dismissed_by=actor_id, dismissed_at=NOW,
        )

    api, commits = _api(body={"reason": " Hai mức khác nhau "}, dismiss=dismiss)
    status, payload = api.dismiss_contradiction(4)
    assert status == 200 and commits == [True] and received == [(4, "Hai mức khác nhau", 3)]
    assert payload["contradiction"]["dismissed_by_name"] == "Bao Reviewer"
    assert payload["contradiction"]["found_by"] == "ai"


def test_a_dismissal_without_a_reason_or_of_an_unknown_row_saves_nothing():
    api, commits = _api(body={"reason": ""})
    assert api.dismiss_contradiction(4)[0] == 400

    def missing(contradiction_id, reason, actor_id):
        raise ContradictionNotFoundError()

    api, commits = _api(body={"reason": "x"}, dismiss=missing)
    assert api.dismiss_contradiction(99) == (404, {"message": ContradictionNotFoundError.message})
    assert commits == []


def test_only_an_administrator_checks_or_dismisses():
    api, commits = _api(admin=False, body={"reason": "x"})
    assert api.check_contradictions() == (403, {"message": "Admin access required."})
    assert api.dismiss_contradiction(4) == (403, {"message": "Admin access required."})
    assert commits == []
