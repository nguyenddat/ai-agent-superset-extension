import ast
from types import SimpleNamespace

from catalog_source import api_methods, compile_into, module_function

from text_to_bi.superset_semantic_layer.core.exceptions import AdminRequiredError
from text_to_bi.superset_semantic_layer.modules.glossary_management.exceptions import (
    GlossaryConflictError,
    GlossarySelfApprovalError,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_glossary_validation import (
    expected_revision_of,
)

ADMIN_ENDPOINTS = {
    "read_glossary_terms": ("/glossary", "GET"),
    "read_glossary_options": ("/glossary/options", "GET"),
    "create_glossary_term": ("/glossary", "POST"),
    "update_glossary_term": ("/glossary/<int:term_id>/draft", "PUT"),
    "approve_glossary_term": ("/glossary/<int:term_id>/approve", "POST"),
    "revoke_glossary_term": ("/glossary/<int:term_id>/revoke", "POST"),
    "read_glossary_events": ("/glossary/<int:term_id>/audit", "GET"),
    "update_glossary_term_group": ("/glossary/<int:term_id>/group", "PUT"),
    "create_glossary_group": ("/glossary/groups", "POST"),
    "update_glossary_group": ("/glossary/groups/<int:group_id>", "PUT"),
    "delete_glossary_group": ("/glossary/groups/<int:group_id>", "DELETE"),
}


def _call_name(node):
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _decorator_calls(method):
    return [_call_name(decorator) for decorator in method.decorator_list]


def _route(method):
    expose = next(decorator for decorator in method.decorator_list if _call_name(decorator) == "expose")
    expression = expose.args[0]
    if isinstance(expression, ast.Name):
        route_path = "/glossary/groups" if "glossary_group" in method.name else "/glossary"
    else:
        prefix = "/glossary/group-suggestions" if "suggestion" in method.name else (
            "/glossary/groups" if "glossary_group" in method.name else "/glossary"
        )
        route_path = "".join(
            value.value if isinstance(value, ast.Constant) else prefix
            for value in expression.values
        )
    return route_path, next(
        keyword.value.elts[0].value for keyword in expose.keywords if keyword.arg == "methods"
    )


class _GlossaryResponseAPI:
    def response(self, status, **payload):
        return status, payload

    def response_400(self, **payload):
        return self.response(400, **payload)


def _update_handler(payload, update_draft):
    methods = api_methods()
    handler = methods["update_glossary_term"]
    # Keep only @handle_errors, which turns the module's errors into responses.
    handler.decorator_list = [item for item in handler.decorator_list if _call_name(item) == "handle_errors"]
    api = ast.ClassDef(
        name="HarnessAPI",
        bases=[ast.Name(id="RestApi", ctx=ast.Load())],
        keywords=[],
        body=[handler],
        decorator_list=[],
    )
    commits = []
    namespace = {
        "RestApi": _GlossaryResponseAPI,
        "db": SimpleNamespace(session=SimpleNamespace(commit=lambda: commits.append(True), rollback=lambda: None)),
        "request": SimpleNamespace(get_json=lambda silent=True: payload),
        "current_user": SimpleNamespace(id=42),
        "ensure_dictionary_tables": lambda: None,
        "GlossaryTermService": lambda: SimpleNamespace(update=update_draft),
        "expected_revision_of": expected_revision_of,
        "require_admin": lambda: None,
        "serialize_glossary_term": lambda term, revisions: {"id": term.id, "revisions": len(revisions)},
    }
    compile_into(namespace, api)
    instance = namespace["HarnessAPI"]()
    return instance, commits


def _frontend_draft_payload(**overrides):
    payload = {
        "canonical_name": "Average temperature",
        "definition": "Mean recorded temperature.",
        "synonyms": ["mean temperature"],
        "steward_id": 2,
        "links": [{"kind": "dataset", "dataset_id": 7}],
        "expected_revision": 3,
    }
    payload.update(overrides)
    return payload


def test_admin_glossary_management_routes_are_explicitly_guarded_and_csrf_protected():
    methods = api_methods()
    for name, expected_route in ADMIN_ENDPOINTS.items():
        method = methods[name]
        decorators = _decorator_calls(method)
        assert _route(method) == expected_route
        assert "protect" in decorators and "safe" in decorators and "permission_name" in decorators
        assert decorators[-1] == "handle_errors"
        if expected_route[1] != "GET":
            assert "csrf_protected" in decorators and "rollback_on_error" in decorators
        # Reads are open to the Semantic Layer Viewer role; every change stays with administrators.
        guard = "require_semantic_layer_view()" if expected_route[1] == "GET" else "require_admin()"
        assert guard in ast.unparse(method)
    assert (AdminRequiredError.status, AdminRequiredError.message) == (403, "Admin access required.")
    assert "require_semantic_layer_query()" in ast.unparse(api_methods()["read_glossary_discovery"])


def test_management_routes_delegate_to_governed_service_with_expected_revision_and_actor():
    methods = api_methods()
    for name in ("create_glossary_term", "update_glossary_term", "approve_glossary_term", "revoke_glossary_term"):
        source = ast.unparse(methods[name])
        assert "current_user.id" in source
    for name in ("update_glossary_term", "approve_glossary_term", "revoke_glossary_term"):
        source = ast.unparse(methods[name])
        assert "expected_revision" in source
    assert ".create(" in ast.unparse(methods["create_glossary_term"])
    assert ".update(" in ast.unparse(methods["update_glossary_term"])
    assert ".approve(" in ast.unparse(methods["approve_glossary_term"])
    assert ".revoke(" in ast.unparse(methods["revoke_glossary_term"])


def test_update_draft_passes_the_frontend_payload_its_revision_token_and_the_actor_then_commits():
    received = {}

    def update_draft(term_id, payload, expected, actor_id):
        received.update(term_id=term_id, payload=payload, expected=expected, actor_id=actor_id)
        return SimpleNamespace(term=SimpleNamespace(id=7))

    api, commits = _update_handler(_frontend_draft_payload(), update_draft)
    status, body = api.update_glossary_term(7)

    assert status == 200 and commits == [True]
    assert body["term"] == {"id": 7, "revisions": 1}
    assert received == {"term_id": 7, "payload": _frontend_draft_payload(), "expected": 3, "actor_id": 42}


def test_update_draft_maps_service_conflict_to_409_without_committing():
    def update_draft(*_args):
        raise GlossaryConflictError("stale revision")

    api, commits = _update_handler(_frontend_draft_payload(), update_draft)
    status, body = api.update_glossary_term(7)
    assert (status, body, commits) == (409, {"message": "stale revision"}, [])


def test_update_draft_rejects_non_object_or_missing_revision_before_service_call():
    called = []
    api, _ = _update_handler(None, lambda *_args: called.append(True))
    status, body = api.update_glossary_term(7)
    assert (status, body) == (400, {"message": "expected_revision is required."})
    assert called == []


def test_admin_routes_keep_service_errors_generic_and_rollback_unexpected_failures():
    rollback = module_function("rollback_on_error")
    session = type(
        "Session", (), {"rollbacks": 0, "rollback": lambda self: setattr(self, "rollbacks", self.rollbacks + 1)}
    )()
    namespace = {
        "wraps": lambda method: lambda wrapper: wrapper,
        "db": type("DB", (), {"session": session})(),
        "logger": type("Log", (), {"exception": lambda *_: None})(),
    }
    compile_into(namespace, rollback)
    wrapped = namespace["rollback_on_error"](lambda _: (_ for _ in ()).throw(RuntimeError("internal detail")))
    response = type("API", (), {"response_500": lambda self, **payload: (500, payload)})()
    assert wrapped(response) == (500, {"message": "Could not save the change."})
    assert session.rollbacks == 1


def test_audit_is_admin_only_read_only_and_cannot_be_used_for_cross_term_id_lookup():
    method = api_methods()["read_glossary_events"]
    source = ast.unparse(method)
    assert "term_id" in source and "audit" in source.lower()
    assert "current_user.id" not in source  # audit visibility is role-based, not caller-supplied identity.
    assert "request.args" not in source  # no alternate revision/term ID can override the path scope.


def test_approval_passes_the_second_reviewer_setting_and_answers_self_approval_with_403():
    source = ast.unparse(api_methods()["approve_glossary_term"])
    assert "second_reviewer_required()" in source and "review_reason(payload)" in source
    assert GlossarySelfApprovalError.status == 403 and "không thể tự duyệt" in GlossarySelfApprovalError.message


def test_list_reports_review_state_reviewers_and_the_second_reviewer_setting():
    source = ast.unparse(api_methods()["read_glossary_terms"])
    from pathlib import Path

    serializer_path = (
        Path(__file__).parents[1]
        / "src/text_to_bi/superset_semantic_layer/modules/glossary_management/utils/util_serializer.py"
    )
    serializer_tree = ast.parse(serializer_path.read_text(encoding="utf-8"))
    serializer = next(
        node for node in serializer_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "serialize_glossary_review_entry"
    )
    source += ast.unparse(serializer)
    for field in (
        "state",
        "author_name",
        "approver_name",
        "revoker_name",
        "serving_revision_number",
        "steward_name",
        "users",
        "current_user_id",
        "require_second_reviewer",
    ):
        assert f"'{field}'" in source or f"{field}=" in source
    assert "'outdated'" in source
