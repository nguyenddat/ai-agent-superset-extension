import ast
import hashlib
import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from catalog_source import MODULES_PATH, api_class, api_methods, compile_into
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base
from test_expert_rule_service import _lifecycle_resolvers, _lifecycle_session
from test_expert_rule_service import _payload as _rule_payload
from test_glossary_service import _payload as _term_payload
from test_glossary_service import _sqlite_service

from text_to_bi.superset_semantic_layer.common.utils.similarity import (
    NeighbourCluster,
    neighbour_clusters,
    similarity_matrix,
    text_words,
    tfidf_vectors,
)
from text_to_bi.superset_semantic_layer.core.exceptions import AdminRequiredError
from text_to_bi.superset_semantic_layer.modules.expert_rules.exceptions import ExpertRuleValidationError
from text_to_bi.superset_semantic_layer.modules.expert_rules.services import expert_rule as rule_service
from text_to_bi.superset_semantic_layer.modules.expert_rules.services import expert_rule_group as rule_group_service
from text_to_bi.superset_semantic_layer.modules.glossary.exceptions import (
    GlossaryConflictError,
    GlossaryValidationError,
)

EMBEDDING_PATH = MODULES_PATH / "glossary" / "services" / "embedding.py"
SUGGESTION_PATH = MODULES_PATH / "glossary" / "services" / "group_suggestion.py"
RULE_SUGGESTION_PATH = MODULES_PATH / "expert_rules" / "services" / "rule_group_suggestion.py"
GLOSSARY_ENDPOINTS = {
    "glossary_group_suggestions": ("/glossary/group-suggestions", "GET"),
    "apply_glossary_group_suggestion": ("/glossary/group-suggestions/apply", "POST"),
    "dismiss_glossary_group_suggestion": ("/glossary/group-suggestions/dismiss", "POST"),
}
SUGGESTION_GLOBALS = {
    "hashlib": hashlib,
    "re": re,
    "Sequence": Sequence,
    "dataclass": dataclass,
    "datetime": datetime,
    "timezone": timezone,
    "Any": Any,
    "NeighbourCluster": NeighbourCluster,
    "neighbour_clusters": neighbour_clusters,
    "similarity_matrix": similarity_matrix,
}


def _run_source(namespace: dict, path) -> dict:
    """Run a module's definitions, without its imports, with `namespace` as their globals."""
    namespace.setdefault("__name__", path.stem)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return namespace


# Similarity and clustering


def test_words_compare_equal_whatever_the_case_or_unicode_form():
    decomposed = unicodedata.normalize("NFD", "Lượng MƯA")
    assert text_words(decomposed) == text_words("lượng mưa") == ["lượng", "mưa"]


def test_tfidf_puts_texts_sharing_words_closer_than_unrelated_ones():
    similarity = similarity_matrix(
        tfidf_vectors(["Mưa lớn. Ngày có lượng mưa trên 50 mm", "Ngày có mưa", "Gió mạnh. Gió giật từ cấp 6"])
    )
    assert similarity[0][1] > 0.25 > similarity[0][2]
    assert similarity[0][0] == pytest.approx(1.0)


def test_clusters_suggest_a_new_group_and_a_move_into_an_existing_group_on_fixed_vectors():
    vectors = [[1, 0, 0], [0.9, 0.1, 0], [0, 1, 0], [0, 0.9, 0.3], [0, 0, 1]]
    clusters = neighbour_clusters([None, None, None, 7, None], similarity_matrix(vectors), 0.7)
    assert sorted(clusters, key=lambda cluster: cluster.member_indexes) == [
        NeighbourCluster(None, (0, 1), ()),
        NeighbourCluster(7, (2,), (3,)),
    ]


def test_existing_groups_never_merge_and_average_linkage_does_not_chain():
    two_groups = neighbour_clusters([1, 2], [[1, 0.99], [0.99, 1]], 0.7)
    assert two_groups == []
    # A is close to B and B to C, but A is far from C: only A and B are put together.
    chain = [[1, 0.8, 0.1], [0.8, 1, 0.8], [0.1, 0.8, 1]]
    assert neighbour_clusters([None, None, None], chain, 0.7) == [NeighbourCluster(None, (0, 1), ())]


# Embedding and its fallback


def _embedding_service(api_key="secret", responses=None):
    """embedding.py with fake settings, HTTP and cache; `responses` gives each call's vectors, or "fail"."""
    rows, calls = [], []

    class RequestException(Exception):
        pass

    def post(url, headers, json, timeout):
        calls.append({"url": url, "input": json["input"], "model": json["model"]})
        answer = responses.pop(0)
        if answer == "fail":
            raise RequestException("timeout")
        data = [{"index": index, "embedding": vector} for index, vector in enumerate(answer)]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": list(reversed(data))})

    repository = SimpleNamespace(
        vectors_for=lambda model, hashes: {
            row.content_hash: row.vector for row in rows if row.model == model and row.content_hash in hashes
        },
        add=lambda row, flush=True: rows.append(row),
    )
    settings = SimpleNamespace(
        OPENROUTER_API_KEY=api_key,
        OPENROUTER_EMBEDDING_MODEL="test/embedding",
        OPENROUTER_BASE_URL="https://openrouter.test/api/v1/",
    )
    namespace = _run_source(
        {
            "settings": settings,
            "requests": SimpleNamespace(RequestException=RequestException, post=post),
            "text_embedding_repository": lambda: repository,
            "TextEmbedding": lambda **values: SimpleNamespace(**values),
            "tfidf_vectors": tfidf_vectors,
            "hashlib": hashlib,
            "logging": logging,
            "dataclass": dataclass,
            "datetime": datetime,
            "timezone": timezone,
            "Any": Any,
        },
        EMBEDDING_PATH,
    )
    return namespace, rows, calls


def test_without_a_key_texts_are_compared_by_tfidf_and_nothing_is_requested():
    namespace, rows, calls = _embedding_service(api_key="")
    vectors = namespace["text_vectors"](["Mưa lớn", "Ngày có mưa"])
    assert (vectors.method, vectors.model, calls, rows) == ("tfidf", None, [], [])
    assert vectors.vectors == tfidf_vectors(["Mưa lớn", "Ngày có mưa"])


# A failed request, and an answer with one vector for two texts.
@pytest.mark.parametrize("answer", ["fail", [[0.1, 0.2]]])
def test_a_failed_or_malformed_embedding_call_falls_back_to_tfidf(answer):
    namespace, rows, calls = _embedding_service(responses=[answer])
    vectors = namespace["text_vectors"](["Mưa lớn", "Ngày có mưa"])
    assert (vectors.method, len(calls), rows) == ("tfidf", 1, [])


def test_vectors_are_cached_by_text_hash_and_only_new_texts_are_requested():
    namespace, rows, calls = _embedding_service(responses=[[[1.0, 0.0], [0.0, 1.0]], [[0.6, 0.8]]])
    first = namespace["text_vectors"](["Mưa lớn", "Ngày có mưa", "Mưa lớn"])
    assert (first.method, first.model) == ("embedding", "test/embedding")
    assert first.vectors == [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
    assert calls[0]["url"] == "https://openrouter.test/api/v1/embeddings"
    assert calls[0]["input"] == ["Mưa lớn", "Ngày có mưa"] and len(rows) == 2

    second = namespace["text_vectors"](["Ngày có mưa", "Độ ẩm"])
    assert second.vectors == [[0.0, 1.0], [0.6, 0.8]]
    assert calls[1]["input"] == ["Độ ẩm"] and len(rows) == 3
    expected_hashes = {namespace["text_hash"](text) for text in ("Mưa lớn", "Ngày có mưa", "Độ ẩm")}
    assert {row.content_hash for row in rows} == expected_hashes


# Glossary suggestions on SQLite

VECTORS = {
    "Gió mạnh": [1, 0, 0],
    "Gió giật": [0.9, 0.1, 0],
    "Mưa lớn": [0, 1, 0],
    "Ngày có mưa": [0, 0.9, 0.2],
    "Mưa to": [0, 0.95, 0.1],
    "Độ ẩm": [0, 0, 1],
}


def _glossary_grouping():
    """The glossary services on SQLite with a dismissal table and term vectors taken from VECTORS by name."""
    service, session = _sqlite_service()
    namespace = service.create_draft.__globals__
    base = declarative_base()

    class GroupSuggestionDismissal(base):
        __tablename__ = "group_suggestion_dismissal"
        id = Column(Integer, primary_key=True)
        kind = Column(String, nullable=False)
        fingerprint = Column(String, nullable=False)
        dismissed_by = Column(Integer)
        dismissed_at = Column(DateTime, nullable=False)

    base.metadata.create_all(session.get_bind())
    namespace.update(SUGGESTION_GLOBALS)
    namespace["GroupSuggestionDismissal"] = GroupSuggestionDismissal
    namespace["text_vectors"] = lambda texts: SimpleNamespace(
        method="embedding", model="test/embedding", vectors=[VECTORS[text.split(".")[0]] for text in texts]
    )
    _run_source(namespace, SUGGESTION_PATH)
    return namespace, session, GroupSuggestionDismissal


def _term(namespace, name, group_id=None):
    return namespace["create_draft"](_term_payload(canonical_name=name, definition=f"{name}.", group_id=group_id), 7)


def _by_target(result):
    return {(suggestion["group"] or {}).get("name"): suggestion for suggestion in result["suggestions"]}


def test_term_suggestions_propose_a_new_group_and_a_move_into_a_close_existing_group():
    namespace, session, _ = _glossary_grouping()
    wind = namespace["create_group"]({"name": "Gió"})
    strong_wind = _term(namespace, "Gió mạnh", wind.id).term_id
    gust = _term(namespace, "Gió giật").term_id
    heavy_rain = _term(namespace, "Mưa lớn").term_id
    rainy_day = _term(namespace, "Ngày có mưa").term_id
    _term(namespace, "Độ ẩm")
    session.commit()

    result = namespace["suggest_term_groups"]()

    assert (result["method"], result["model"], result["threshold"]) == ("embedding", "test/embedding", 0.7)
    suggestions = _by_target(result)
    assert set(suggestions) == {"Gió", None}
    move = suggestions["Gió"]
    assert move["group"] == {"id": wind.id, "name": "Gió"} and move["proposed_name"] == "Gió"
    assert [member["id"] for member in move["members"]] == [gust]
    assert move["members"][0]["closest"]["name"] == "Gió mạnh" and move["members"][0]["similarity"] > 0.9
    assert move["group_members"] == [{"id": strong_wind, "name": "Gió mạnh"}]
    new_group = suggestions[None]
    assert new_group["proposed_name"] == "Mưa lớn" and new_group["group_members"] == []
    assert sorted(member["id"] for member in new_group["members"]) == [heavy_rain, rainy_day]
    assert new_group["fingerprint"] == namespace["suggestion_fingerprint"](None, [rainy_day, heavy_rain])


def test_a_dismissed_suggestion_stays_hidden_until_its_members_change():
    namespace, session, dismissal_model = _glossary_grouping()
    _term(namespace, "Mưa lớn")
    _term(namespace, "Ngày có mưa")
    session.commit()
    fingerprint = namespace["suggest_term_groups"]()["suggestions"][0]["fingerprint"]

    for _ in range(2):
        assert namespace["dismiss_suggestion"]("glossary", {"fingerprint": fingerprint}, 8, GlossaryValidationError)
        session.commit()
    assert session.query(dismissal_model).count() == 1
    assert namespace["suggest_term_groups"]()["suggestions"] == []
    # Rules keep their own dismissals.
    assert namespace["group_suggestion_dismissal_repository"]().fingerprints("expert_rule") == set()

    _term(namespace, "Mưa to")
    session.commit()
    suggestions = namespace["suggest_term_groups"]()["suggestions"]
    assert [len(suggestion["members"]) for suggestion in suggestions] == [3]
    assert suggestions[0]["fingerprint"] != fingerprint

    with pytest.raises(GlossaryValidationError, match="không hợp lệ"):
        namespace["dismiss_suggestion"]("glossary", {"fingerprint": "abc"}, 8, GlossaryValidationError)


def test_applying_a_changed_suggestion_moves_terms_without_review_and_audits_each_move():
    namespace, session, _ = _glossary_grouping()
    wind = namespace["create_group"]({"name": "Gió"})
    _term(namespace, "Gió mạnh", wind.id)
    gust = _term(namespace, "Gió giật").term_id
    heavy_rain = _term(namespace, "Mưa lớn").term_id
    rainy_day = _term(namespace, "Ngày có mưa").term_id
    namespace["approve_revision"](gust, 1, 8, None, False)
    session.commit()

    group, moved = namespace["apply_term_grouping"]({"member_ids": [gust], "group_id": wind.id}, 8)
    assert (group.id, moved) == (wind.id, [gust])
    # The administrator renamed the new group and unticked "Ngày có mưa".
    group, moved = namespace["apply_term_grouping"]({"member_ids": [heavy_rain, heavy_rain], "group_name": "Mưa"}, 8)
    session.commit()
    assert (group.name, moved) == ("Mưa", [heavy_rain])

    terms = namespace["glossary_term_repository"]()
    assert terms.get(gust).group_id == wind.id and terms.get(heavy_rain).group_id == group.id
    revisions = namespace["glossary_term_revision_repository"]()
    assert [revision.revision_number for revision in revisions.for_term(gust)] == [1]
    assert revisions.serving_for(gust).status == "approved"
    events = namespace["glossary_term_audit_event_repository"]().for_term(gust)
    assert [(event.event_type, event.reason) for event in events][-1] == ("moved", "Chưa phân nhóm → Gió")
    # The unticked term is now suggested for the group just created.
    suggestions = namespace["suggest_term_groups"]()["suggestions"]
    assert [suggestion["group"]["name"] for suggestion in suggestions] == ["Mưa"]
    assert [member["id"] for member in suggestions[0]["members"]] == [rainy_day]

    with pytest.raises(GlossaryConflictError):
        namespace["apply_term_grouping"]({"member_ids": [rainy_day], "group_name": " mưa "}, 8)
    no_members, flag_member = {"member_ids": []}, {"member_ids": [True]}
    for payload in (no_members, flag_member, {"member_ids": [1], "group_id": "2"}, {"member_ids": [1]}):
        with pytest.raises(GlossaryValidationError):
            namespace["apply_term_grouping"](payload, 8)


# Expert rule grouping


def test_applying_a_rule_suggestion_creates_the_group_and_audits_the_move(monkeypatch):
    session, rule_model, _, audit_model = _lifecycle_session(monkeypatch)
    created = rule_service.create_draft(session, _rule_payload(), 11, *_lifecycle_resolvers())
    session.commit()
    namespace = _run_source(
        {
            **SUGGESTION_GLOBALS,
            "create_rule_group": rule_group_service.create_rule_group,
            "move_rule": rule_group_service.move_rule,
            "require_rule_group": rule_group_service.require_rule_group,
            "ExpertRuleValidationError": ExpertRuleValidationError,
        },
        SUGGESTION_PATH,
    )
    _run_source(namespace, RULE_SUGGESTION_PATH)

    payload = {"member_ids": [created.rule_id], "group_name": "Lọc"}
    group, moved = namespace["apply_rule_grouping"](session, payload, 12)
    session.commit()

    assert moved == [created.rule_id] and session.get(rule_model, created.rule_id).group_id == group.id
    events = [(event.event_type, event.reason) for event in session.query(audit_model).order_by(audit_model.id)]
    assert events == [("created", None), ("moved", "Chưa phân nhóm → Lọc")]
    with pytest.raises(ExpertRuleValidationError):
        namespace["apply_rule_grouping"](session, {"member_ids": "1"}, 12)


def test_a_rule_is_embedded_from_its_name_terms_conditions_and_examples():
    namespace = _run_source({"Any": Any}, RULE_SUGGESTION_PATH)
    columns = SimpleNamespace(get=lambda column_id: SimpleNamespace(display_name="Lượng mưa", column_name="luong_mua"))
    condition = {"field_ref": {"column_dictionary_id": 96}, "operator": "greater_than_or_equal", "value": 50}
    text = namespace["rule_text"](
        "Ngày mưa lớn",
        ["Mưa lớn"],
        [namespace["_condition_text"](condition, columns)],
        [{"question": "Tháng nào mưa lớn?", "intent": "Đếm ngày mưa lớn"}],
    )
    assert text == (
        "Ngày mưa lớn. Thuật ngữ: Mưa lớn. Điều kiện: Lượng mưa từ 50. Câu hỏi: Tháng nào mưa lớn? (Đếm ngày mưa lớn)"
    )


# Routes


def _call_name(node):
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def test_suggestion_routes_are_admin_only_and_writes_follow_the_decorator_order():
    methods = api_methods()
    for name, (path, verb) in GLOSSARY_ENDPOINTS.items():
        method = methods[name]
        decorators = [_call_name(decorator) for decorator in method.decorator_list]
        expose = method.decorator_list[0]
        assert (expose.args[0].value, expose.keywords[0].value.elts[0].value) == (path, verb)
        expected = ["expose", "protect", "safe", "permission_name"]
        if verb != "GET":
            expected += ["csrf_protected", "rollback_on_error"]
        assert decorators == [*expected, "handle_errors"]
        assert "require_admin()" in ast.unparse(method)


class _ResponseAPI:
    def response(self, status, **payload):
        return status, payload


def _suggestion_api(payload=None, **fakes):
    session = SimpleNamespace(commits=0, rollbacks=0, failing_commit=None)

    def commit():
        if session.failing_commit:
            raise session.failing_commit
        session.commits += 1

    session.commit = commit
    session.rollback = lambda: setattr(session, "rollbacks", session.rollbacks + 1)
    namespace = {
        "RestApi": _ResponseAPI,
        "db": SimpleNamespace(session=session),
        "request": SimpleNamespace(get_json=lambda silent=True: payload),
        "current_user": SimpleNamespace(id=42),
        "ensure_dictionary_tables": lambda: None,
        "require_admin": lambda: None,
        "IntegrityError": IntegrityError,
        **fakes,
    }
    compile_into(namespace, api_class({*GLOSSARY_ENDPOINTS, "_glossary_group"}))
    return namespace["SemanticLayerAPI"](), session


def test_apply_route_commits_once_and_answers_a_taken_group_name_with_409():
    received = {}

    def apply_term_grouping(payload, actor_id):
        received.update(payload=payload, actor_id=actor_id)
        return SimpleNamespace(id=3, name="Mưa", description=None), [5, 6]

    payload = {"member_ids": [5, 6], "group_name": "Mưa"}
    api, session = _suggestion_api(payload, apply_term_grouping=apply_term_grouping)
    assert api.apply_glossary_group_suggestion() == (
        200, {"group": {"id": 3, "name": "Mưa", "description": None}, "moved_term_ids": [5, 6]}
    )
    assert received == {"payload": payload, "actor_id": 42} and session.commits == 1

    def taken(*_):
        raise GlossaryConflictError("Đã có nhóm thuật ngữ cùng tên.")

    api, session = _suggestion_api(payload, apply_term_grouping=taken)
    assert api.apply_glossary_group_suggestion() == (409, {"message": "Đã có nhóm thuật ngữ cùng tên."})
    assert (session.commits, session.rollbacks) == (0, 1)


def test_listing_keeps_its_answer_when_another_request_cached_the_same_embedding_first():
    result = {"method": "embedding", "model": "m", "threshold": 0.7, "suggestions": []}
    api, session = _suggestion_api(suggest_term_groups=lambda: result)
    session.failing_commit = IntegrityError("insert", {}, Exception())
    assert api.glossary_group_suggestions() == (200, result)
    assert session.rollbacks == 1

    def not_admin():
        raise AdminRequiredError()

    api, _ = _suggestion_api(suggest_term_groups=lambda: result, require_admin=not_admin)
    assert api.glossary_group_suggestions() == (403, {"message": "Admin access required."})


def test_dismiss_route_records_the_fingerprint_for_glossary_terms():
    received = {}

    def dismiss_suggestion(kind, payload, actor_id, invalid):
        received.update(kind=kind, payload=payload, actor_id=actor_id, invalid=invalid)
        return "f" * 64

    api, session = _suggestion_api(
        {"fingerprint": "f" * 64}, dismiss_suggestion=dismiss_suggestion, GLOSSARY_KIND="glossary"
    )
    assert api.dismiss_glossary_group_suggestion() == (200, {"fingerprint": "f" * 64})
    assert received == {
        "kind": "glossary", "payload": {"fingerprint": "f" * 64}, "actor_id": 42, "invalid": GlossaryValidationError
    }
    assert session.commits == 1
