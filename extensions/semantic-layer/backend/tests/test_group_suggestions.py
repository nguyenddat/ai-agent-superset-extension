import ast
import hashlib
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from catalog_source import MODULES_PATH, api_class, api_methods, compile_into
from sqlalchemy.exc import IntegrityError
from test_glossary_service import _current_glossary_service
from test_glossary_service import _payload as _term_payload

from text_to_bi.superset_semantic_layer.common.utils.similarity import (
    NeighbourCluster,
    neighbour_clusters,
    similarity_matrix,
    text_words,
    tfidf_vectors,
)
from text_to_bi.superset_semantic_layer.core.exceptions import AdminRequiredError
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.exceptions import ExpertRuleValidationError
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import srv_expert_rule_group as rule_group_service
from text_to_bi.superset_semantic_layer.modules.glossary_management.exceptions import (
    GlossaryConflictError,
    GlossaryValidationError,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.services import srv_group_suggestion
from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_glossary_group import GlossaryGroupService

EMBEDDING_PATH = MODULES_PATH / "glossary_management" / "services" / "srv_glossary_embedding.py"
RULE_SUGGESTION_PATH = MODULES_PATH / "expert_rule_management" / "services" / "srv_expert_rule_group.py"
GLOSSARY_ENDPOINTS = {
    "read_glossary_group_suggestions": ("/glossary/group-suggestions", "GET", "suggestion_prefix"),
    "apply_glossary_group_suggestion": (
        "/glossary/group-suggestions/apply", "POST", "f'{suggestion_prefix}/apply'"
    ),
    "dismiss_glossary_group_suggestion": (
        "/glossary/group-suggestions/dismiss", "POST", "f'{suggestion_prefix}/dismiss'"
    ),
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
        read_vectors=lambda model, hashes: {
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
    assert calls[0]["input"] == ["Mưa lớn", "Ngày có mưa"] and rows == []

    # This service reads persisted vectors; cache population is a separate write operation.
    rows.append(SimpleNamespace(model="test/embedding", content_hash=namespace["text_hash"]("Ngày có mưa"), vector=[0.0, 1.0]))
    second = namespace["text_vectors"](["Ngày có mưa", "Độ ẩm"])
    assert second.vectors == [[0.0, 1.0], [0.6, 0.8]]
    assert calls[1]["input"] == ["Độ ẩm"] and len(rows) == 1
    assert rows[0].content_hash == namespace["text_hash"]("Ngày có mưa")


# Glossary suggestions on SQLite

VECTORS = {
    "Gió mạnh": [1, 0, 0],
    "Gió giật": [0.9, 0.1, 0],
    "Mưa lớn": [0, 1, 0],
    "Ngày có mưa": [0, 0.9, 0.2],
    "Mưa to": [0, 0.95, 0.1],
    "Độ ẩm": [0, 0, 1],
}


def _glossary_grouping(monkeypatch):
    """Combine the current term and group services with small in-memory repositories."""
    term_service, session = _current_glossary_service(monkeypatch)
    term_records = []
    group_records = {}
    dismissed: dict[tuple[str, str], dict[str, Any]] = {}
    audit_events = term_service.events

    class GroupRepository:
        def read_by_normalized_name(self, normalized_name):
            return next((group for group in group_records.values() if group.normalized_name == normalized_name), None)

        def read(self, group_id):
            return group_records.get(group_id)

        def read_all(self):
            return list(group_records.values())

        def create(self, values):
            group = SimpleNamespace(id=max(group_records, default=0) + 1, **values)
            group_records[group.id] = group
            return group

        def require(self, group_id):
            group = self.read(group_id)
            if group is None:
                raise GlossaryValidationError("Unknown glossary group.")
            return group

        def place_term(self, term, group, actor_id):
            previous = term.group
            if (previous.id if previous else None) == (group.id if group else None):
                return
            term.group, term.group_id = group, group.id if group else None
            revision = term_service.revisions.read_current(term.id)
            if revision is not None:
                old_name = previous.name if previous else "Chưa phân nhóm"
                new_name = group.name if group else "Chưa phân nhóm"
                audit_events.create(revision, "moved", actor_id, f"{old_name} → {new_name}")

    class DismissalRepository:
        def read_fingerprints(self, kind):
            return {fingerprint for stored_kind, fingerprint in dismissed if stored_kind == kind}

        def create(self, values, flush=False):
            dismissed[(values["kind"], values["fingerprint"])] = values

        def fingerprints(self, kind):
            return self.read_fingerprints(kind)

    group_repository = GroupRepository()
    dismissal_repository = DismissalRepository()
    term_service.groups = group_repository
    term_service.terms.read_all = lambda: list(term_records)
    group_service = GlossaryGroupService.__new__(GlossaryGroupService)
    group_service.groups = group_repository
    group_service.terms = term_service.terms
    group_service.revisions = term_service.revisions
    group_service.events = audit_events
    monkeypatch.setattr(srv_group_suggestion, "group_suggestion_dismissal_repository", lambda: dismissal_repository)
    monkeypatch.setattr(
        srv_group_suggestion,
        "text_vectors",
        lambda texts: SimpleNamespace(
            method="embedding", model="test/embedding", vectors=[VECTORS[text.split(".")[0]] for text in texts]
        ),
    )
    return {
        "create_term": lambda payload, actor_id: _create_term(term_service, term_records, payload, actor_id),
        "create_group": group_service.create,
        "suggest_term_groups": group_service.suggest,
        "apply_term_grouping": group_service.apply_suggestion,
        "dismiss_term_suggestion": group_service.dismiss_suggestion,
        "group_suggestion_dismissal_repository": lambda: dismissal_repository,
        "suggestion_fingerprint": srv_group_suggestion.suggestion_fingerprint,
        "approve_term": term_service.approve,
        "term_service": term_service,
        "group_service": group_service,
        "term_records": term_records,
        "audit_events": audit_events,
    }, session, dismissal_repository


def _create_term(service, term_records, payload, actor_id):
    revision = service.create(payload, actor_id)
    if payload.get("group_id") is not None:
        revision.term.group_id = payload["group_id"]
    term_records.append(revision.term)
    return revision


def _term(namespace, name, group_id=None):
    return namespace["create_term"](
        _term_payload(canonical_name=name, definition=f"{name}.", group_id=group_id), 7
    )


def _by_target(result):
    return {(suggestion["group"] or {}).get("name"): suggestion for suggestion in result["suggestions"]}


def test_term_suggestions_propose_a_new_group_and_a_move_into_a_close_existing_group(monkeypatch):
    namespace, session, _ = _glossary_grouping(monkeypatch)
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


def test_a_dismissed_suggestion_stays_hidden_until_its_members_change(monkeypatch):
    namespace, session, dismissal_repository = _glossary_grouping(monkeypatch)
    _term(namespace, "Mưa lớn")
    _term(namespace, "Ngày có mưa")
    session.commit()
    fingerprint = namespace["suggest_term_groups"]()["suggestions"][0]["fingerprint"]

    for _ in range(2):
        assert namespace["dismiss_term_suggestion"]({"fingerprint": fingerprint}, 8)
        session.commit()
    assert len(dismissal_repository.read_fingerprints("glossary")) == 1
    assert namespace["suggest_term_groups"]()["suggestions"] == []
    # Rules keep their own dismissals.
    assert namespace["group_suggestion_dismissal_repository"]().fingerprints("expert_rule") == set()

    _term(namespace, "Mưa to")
    session.commit()
    suggestions = namespace["suggest_term_groups"]()["suggestions"]
    assert [len(suggestion["members"]) for suggestion in suggestions] == [3]
    assert suggestions[0]["fingerprint"] != fingerprint

    with pytest.raises(GlossaryValidationError, match="không hợp lệ"):
        namespace["dismiss_term_suggestion"]({"fingerprint": "abc"}, 8)


def test_applying_a_changed_suggestion_moves_terms_without_review_and_audits_each_move(monkeypatch):
    namespace, session, _ = _glossary_grouping(monkeypatch)
    wind = namespace["create_group"]({"name": "Gió"})
    _term(namespace, "Gió mạnh", wind.id)
    gust = _term(namespace, "Gió giật").term_id
    heavy_rain = _term(namespace, "Mưa lớn").term_id
    rainy_day = _term(namespace, "Ngày có mưa").term_id
    namespace["approve_term"](gust, 1, 8, None, False)
    session.commit()

    group, moved = namespace["apply_term_grouping"]({"member_ids": [gust], "group_id": wind.id}, 8)
    assert (group.id, moved) == (wind.id, [gust])
    # The administrator renamed the new group and unticked "Ngày có mưa".
    group, moved = namespace["apply_term_grouping"]({"member_ids": [heavy_rain, heavy_rain], "group_name": "Mưa"}, 8)
    session.commit()
    assert (group.name, moved) == ("Mưa", [heavy_rain])

    terms = {term.id: term for term in namespace["term_records"]}
    assert terms[gust].group_id == wind.id and terms[heavy_rain].group_id == group.id
    revision = namespace["term_service"].revisions.read_current(gust)
    assert revision.revision_number == 1 and revision.status == "approved"
    events = namespace["term_service"].events.read_history(gust)
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
    rule = SimpleNamespace(id=5, group=None, group_id=None)
    revision = SimpleNamespace(id=9)
    events = []
    groups = {}

    class GroupRepository:
        def read_by_normalized_name(self, _normalized_name):
            return next(
                (group for group in groups.values() if group.normalized_name == _normalized_name), None
            )

        def read(self, group_id):
            return groups.get(group_id)

        def create(self, values):
            group = SimpleNamespace(id=3, **values)
            groups[group.id] = group
            return group

    class RuleRepository:
        def read_for_update(self, rule_id):
            return rule if rule_id == rule.id else None

    class RevisionRepository:
        def read_current(self, rule_id):
            return revision if rule_id == rule.id else None

    class EventService:
        def create(self, current_revision, event_type, actor_id, reason=None):
            events.append((current_revision.id, event_type, actor_id, reason))

    monkeypatch.setattr(rule_group_service, "expert_rule_group_repository", GroupRepository)
    monkeypatch.setattr(rule_group_service, "expert_rule_repository", RuleRepository)
    monkeypatch.setattr(rule_group_service, "expert_rule_revision_repository", RevisionRepository)
    monkeypatch.setattr(rule_group_service, "ExpertRuleEventService", EventService)
    service = rule_group_service.ExpertRuleGroupService()

    group, moved = service.apply_suggestion({"member_ids": [rule.id], "group_name": "Lọc"}, 12)

    assert moved == [rule.id] and rule.group_id == group.id
    assert events == [(revision.id, "moved", 12, "Chưa phân nhóm → Lọc")]
    with pytest.raises(ExpertRuleValidationError):
        service.apply_suggestion({"member_ids": "1"}, 12)


def test_a_rule_is_embedded_from_its_name_terms_conditions_and_examples():
    tree = ast.parse(RULE_SUGGESTION_PATH.read_text(encoding="utf-8"))
    helpers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"rule_text", "_condition_text"}
        or isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "OPERATOR_WORDS" for target in node.targets
        )
    ]
    namespace = {"Any": Any}
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(RULE_SUGGESTION_PATH), "exec"), namespace)  # noqa: S102
    columns = SimpleNamespace(read=lambda column_id: SimpleNamespace(display_name="Lượng mưa", column_name="luong_mua"))
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
    for name, (path, verb, path_expression) in GLOSSARY_ENDPOINTS.items():
        method = methods[name]
        decorators = [_call_name(decorator) for decorator in method.decorator_list]
        expose = method.decorator_list[0]
        assert ast.dump(expose.args[0]) == ast.dump(ast.parse(path_expression, mode="eval").body)
        assert method.decorator_list[0].keywords[0].value.elts[0].value == verb
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

    class _GlossaryGroupService:
        def suggest(self):
            return fakes["suggest_term_groups"]()

        def apply_suggestion(self, request_payload, actor_id):
            return fakes["apply_term_grouping"](request_payload, actor_id)

        @staticmethod
        def dismiss_suggestion(request_payload, actor_id):
            return fakes["dismiss_suggestion"]("glossary", request_payload, actor_id, GlossaryValidationError)

    namespace = {
        "RestApi": _ResponseAPI,
        "db": SimpleNamespace(session=session),
        "request": SimpleNamespace(get_json=lambda silent=True: payload),
        "current_user": SimpleNamespace(id=42),
        "ensure_dictionary_tables": lambda: None,
        "require_admin": lambda: None,
        "IntegrityError": IntegrityError,
        "GlossaryGroupService": _GlossaryGroupService,
        "serialize_glossary_group": lambda group: {
            "id": group.id, "name": group.name, "description": group.description
        },
        **fakes,
    }
    compile_into(namespace, api_class(set(GLOSSARY_ENDPOINTS)))
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
    assert api.read_glossary_group_suggestions() == (200, result)
    assert session.rollbacks == 1

    def not_admin():
        raise AdminRequiredError()

    api, _ = _suggestion_api(suggest_term_groups=lambda: result, require_admin=not_admin)
    assert api.read_glossary_group_suggestions() == (403, {"message": "Admin access required."})


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
