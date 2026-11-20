import ast
import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
from sqlalchemy.exc import IntegrityError

# The repositories import flask_appbuilder's Model; import it before the route loader stubs flask_appbuilder.api.
import text_to_bi.superset_semantic_layer.common.base_repo  # noqa: F401
from text_to_bi.superset_semantic_layer.core.exceptions import (
    DatasetAccessError,
    SemanticLayerQueryRequiredError,
    SemanticLayerViewRequiredError,
)
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.exceptions import (
    ExpertRuleConflictError,
    ExpertRuleGroupNotFoundError,
    ExpertRuleSelfApprovalError,
    ExpertRuleValidationError,
)
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import (
    srv_expert_rule as expert_rule_service,
)
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import (
    srv_expert_rule_link as rule_links,
)
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services.srv_expert_rule import ExpertRuleService
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.utils.util_serializer import (
    serialize_expert_rule,
)

ROUTE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "text_to_bi"
    / "superset_semantic_layer"
    / "modules"
    / "expert_rule_management"
    / "routes"
    / "route_expert_rule.py"
)
API_PATH = ROUTE_PATH.with_name("route_expert_rule_api.py")
DATABASE_PATH = Path(__file__).parents[1] / "src" / "text_to_bi" / "superset_semantic_layer" / "core" / "database.py"
ENDPOINTS = {
    "create_expert_rule": ("/expert-rules", "POST"),
    "update_expert_rule": ("/expert-rules/<int:rule_id>/draft", "PUT"),
    "approve_expert_rule": ("/expert-rules/<int:rule_id>/approve", "POST"),
    "revoke_expert_rule": ("/expert-rules/<int:rule_id>/revoke", "POST"),
    "read_expert_rule_events": ("/expert-rules/<int:rule_id>/audit", "GET"),
    "read_discoverable_expert_rules": ("/expert-rules/discover", "GET"),
    "read_expert_rules": ("/expert-rules", "GET"),
    "read_expert_rule_options": ("/expert-rules/options", "GET"),
    "move_expert_rule": ("/expert-rules/<int:rule_id>/group", "PUT"),
    "create_expert_rule_group": ("/expert-rules/groups", "POST"),
    "update_expert_rule_group": ("/expert-rules/groups/<int:group_id>", "PUT"),
    "delete_expert_rule_group": ("/expert-rules/groups/<int:group_id>", "DELETE"),
    "read_expert_rule_group_suggestions": ("/expert-rules/group-suggestions", "GET"),
    "apply_expert_rule_group_suggestion": ("/expert-rules/group-suggestions/apply", "POST"),
    "dismiss_expert_rule_group_suggestion": ("/expert-rules/group-suggestions/dismiss", "POST"),
}


def _name(node):
    if isinstance(node, ast.Call):
        return _name(node.func)
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def test_routes_are_registered_and_mutations_are_admin_csrf_protected():
    tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))
    methods = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ExpertRuleRoutes"
        for node in node.body
        if isinstance(node, ast.FunctionDef)
    }
    group_tree = ast.parse(ROUTE_PATH.with_name("route_expert_rule_group.py").read_text(encoding="utf-8"))
    methods.update(
        {
            node.name: node
            for node in group_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ExpertRuleGroupRoutes"
            for node in node.body
            if isinstance(node, ast.FunctionDef)
        }
    )
    api_tree = ast.parse(API_PATH.read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.ClassDef) and node.name == "ExpertRuleAPI" for node in api_tree.body)
    for name, (path, verb) in ENDPOINTS.items():
        method = methods[name]
        decorators = [_name(item) for item in method.decorator_list]
        expose = next(item for item in method.decorator_list if _name(item) == "expose")
        path_expression = expose.args[0]
        prefixes = {
            target.id: assignment.value.value
            for assignment in ast.walk(tree if name in {
                "create_expert_rule", "update_expert_rule", "approve_expert_rule", "revoke_expert_rule",
                "read_expert_rule_events", "read_discoverable_expert_rules", "read_expert_rules",
                "read_expert_rule_options", "move_expert_rule",
            } else group_tree)
            if isinstance(assignment, ast.Assign) and isinstance(assignment.value, ast.Constant)
            for target in assignment.targets
            if isinstance(target, ast.Name)
        }
        if isinstance(path_expression, ast.Name):
            exposed_path = prefixes[path_expression.id]
        else:
            exposed_path = "".join(
                value.value
                if isinstance(value, ast.Constant)
                else prefixes[value.value.id]
                for value in path_expression.values
            )
        assert exposed_path == path
        assert next(k.value.elts[0].value for k in expose.keywords if k.arg == "methods") == verb
        assert "protect" in decorators and "safe" in decorators
        text = ast.unparse(method)
        assert decorators[-1] == "handle_errors"
        if verb != "GET":
            assert "csrf_protected" in decorators and "require_admin()" in text
        if name == "read_discoverable_expert_rules":
            assert "read_discoverable" in text


def test_route_has_rollback_and_conflict_handling_without_raw_sql_execution():
    source = ROUTE_PATH.read_text(encoding="utf-8")
    database_tree = ast.parse(DATABASE_PATH.read_text(encoding="utf-8"))
    handle_errors = next(node for node in database_tree.body if getattr(node, "name", None) == "handle_errors")
    assert "db.session.rollback()" in ast.unparse(handle_errors)
    assert "@handle_errors" in source and ExpertRuleConflictError.status == 409
    assert "execute(" not in source
    assert "text(" not in source
    assert "__table__.create" not in source
    assert "_ensure_tables" not in source
    assert "ExpertRuleService().read_discoverable()" in source


class _Query:
    def __init__(self, values):
        self.values = values
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def order_by(self, *_):
        return self

    def all(self):
        return [
            value
            for value in self.values
            if all(getattr(value, key, None) == item for key, item in self.filters.items())
        ]

    def one_or_none(self):
        values = self.all()
        return values[0] if len(values) == 1 else None


def _load_route(monkeypatch, *, csrf_error=False, allowed_datasets=(), permissions=()):
    package = "text_to_bi.superset_semantic_layer.modules.expert_rule_management.routes"
    route_name = f"{package}.route_isolated"
    current_user = SimpleNamespace(id=42, is_authenticated=True, roles=[SimpleNamespace(name="Admin")])
    session = SimpleNamespace(commit_calls=0, rollback_calls=0)
    session.commit = lambda: setattr(session, "commit_calls", session.commit_calls + 1)
    session.rollback = lambda: setattr(session, "rollback_calls", session.rollback_calls + 1)
    session.get = lambda *_: None
    db = SimpleNamespace(session=session)

    def identity_decorator(*args, **kwargs):
        if args and callable(args[0]) and not kwargs:
            return args[0]
        return lambda method: method

    api_module = types.ModuleType("flask_appbuilder.api")
    api_module.expose = api_module.permission_name = api_module.protect = identity_decorator
    api_module.safe = identity_decorator
    login_module = types.ModuleType("flask_login")
    login_module.current_user = current_user
    csrf_module = types.ModuleType("flask_wtf.csrf")
    validation_error = type("ValidationError", (Exception,), {})
    csrf_module.validate_csrf = lambda _: (_ for _ in ()).throw(validation_error()) if csrf_error else None
    wtforms_module = types.ModuleType("wtforms")
    wtforms_module.ValidationError = validation_error
    superset_module = types.ModuleType("superset")
    superset_module.db = db
    reviewer = SimpleNamespace(username="reviewer", get_full_name=lambda: "Bao Reviewer")
    superset_module.security_manager = SimpleNamespace(
        raise_for_access=lambda datasource: (
            None if datasource.id in allowed_datasets else (_ for _ in ()).throw(Exception())
        ),
        get_user_by_id=lambda user_id: reviewer if user_id == 42 else None,
        can_access=lambda permission, view_menu: view_menu == "Text to BI Semantic Layer" and permission in permissions,
    )
    sqla_module = types.ModuleType("superset.connectors.sqla.models")
    sqla_module.SqlaTable = type("SqlaTable", (), {})
    exception_module = types.ModuleType("superset.exceptions")
    exception_module.SupersetSecurityException = Exception
    rest_api_module = types.ModuleType("superset_core.rest_api.api")

    class RestApi:
        def response(self, status, **payload):
            return status, payload

        def response_400(self, **payload):
            return 400, payload

        def response_500(self, **payload):
            return 500, payload

    rest_api_module.RestApi = RestApi
    rest_decorators = types.ModuleType("superset_core.rest_api.decorators")
    rest_decorators.api = identity_decorator
    models = types.ModuleType("text_to_bi.superset_semantic_layer.modules.expert_rule_management.models")
    models.__path__ = [str(ROUTE_PATH.parents[1] / "models")]
    models.ExpertRule = type("ExpertRule", (), {})
    models.ExpertRuleRevision = type("ExpertRuleRevision", (), {})
    models.ExpertRuleLink = type("ExpertRuleLink", (), {})
    models.ExpertRuleAuditEvent = type("ExpertRuleAuditEvent", (), {"id": object()})
    models.ExpertRuleGroup = type("ExpertRuleGroup", (), {"name": object()})
    dictionary = types.ModuleType("text_to_bi.superset_semantic_layer.modules.data_dictionary.models")
    dictionary.__path__ = [str(ROUTE_PATH.parents[2] / "data_dictionary" / "models")]
    dictionary.ColumnDictionary = type("ColumnDictionary", (), {})
    dictionary.DatasetDictionary = type("DatasetDictionary", (), {})
    dictionary.DatasetGrain = type("DatasetGrain", (), {})
    dictionary.ColumnTransformation = type("ColumnTransformation", (), {})
    dictionary.ColumnTransformationSource = type("ColumnTransformationSource", (), {})
    dictionary.RelationshipContract = type("RelationshipContract", (), {})
    glossary = types.ModuleType("text_to_bi.superset_semantic_layer.modules.glossary_management.models")
    glossary.__path__ = [str(ROUTE_PATH.parents[1] / ".." / "glossary_management" / "models")]
    glossary.GlossaryTermLink = type("GlossaryTermLink", (), {})
    glossary.GlossaryTerm = type("GlossaryTerm", (), {})
    glossary.GlossaryTermRevision = type("GlossaryTermRevision", (), {})
    glossary.GlossaryTermAuditEvent = type("GlossaryTermAuditEvent", (), {})
    glossary.GlossaryTermGroup = type("GlossaryTermGroup", (), {})
    glossary.TextEmbedding = type("TextEmbedding", (), {})
    glossary.GroupSuggestionDismissal = type("GroupSuggestionDismissal", (), {})
    metric = types.ModuleType("text_to_bi.superset_semantic_layer.modules.metric_management.models")
    metric.__path__ = [str(ROUTE_PATH.parents[1] / ".." / "metric_management" / "models")]
    for name in ("MetricContract", "MetricContractEvent", "MetricDefinition", "RelationshipContract"):
        setattr(metric, name, type(name, (), {}))
    contracts = types.ModuleType(
        "text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_contract",
    )
    contracts.contract_is_approved_current = lambda *_: True
    contracts.metric_contract_hash = lambda *_: "live"
    core_models = types.ModuleType("superset.models.core")
    core_models.Database = type("Database", (), {})
    stubs = {
        "flask_appbuilder.api": api_module,
        "flask_login": login_module,
        "flask_wtf.csrf": csrf_module,
        "wtforms": wtforms_module,
        "superset": superset_module,
        "superset.connectors.sqla.models": sqla_module,
        "superset.models.core": core_models,
        "superset.exceptions": exception_module,
        "superset_core.rest_api.api": rest_api_module,
        "superset_core.rest_api.decorators": rest_decorators,
        models.__name__: models,
        dictionary.__name__: dictionary,
        glossary.__name__: glossary,
        metric.__name__: metric,
        contracts.__name__: contracts,
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    # The shared checks bind flask_login, CSRF and Superset's db when imported, so import them again with these stubs.
    for name in ("security", "database"):
        monkeypatch.delitem(sys.modules, f"text_to_bi.superset_semantic_layer.core.{name}", raising=False)
    # Repositories bind their models, and the services and routes bind the repository factories, when imported; import
    # them again with these stubs.
    rebound = (".repositories.", ".services.", ".routes.")
    for name in list(sys.modules):
        if name in stubs or not name.startswith("text_to_bi.superset_semantic_layer.modules."):
            continue
        if any(part in name for part in rebound) or name.endswith(".dependencies"):
            monkeypatch.delitem(sys.modules, name)
    spec = importlib.util.spec_from_file_location(route_name, API_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, route_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, current_user, session


def test_mutation_route_enforces_csrf_admin_and_rolls_back_validation_errors(monkeypatch):
    app = Flask(__name__)
    route, user, session = _load_route(monkeypatch, allowed_datasets={7})
    api = route.ExpertRuleAPI()
    with app.test_request_context("/", method="POST", json={}):
        user.roles = []
        assert api.create_expert_rule()[0] == 403
    with app.test_request_context("/", method="POST", json={}):
        user.roles = [SimpleNamespace(name="Admin")]
        user.is_authenticated = False
        assert api.create_expert_rule()[0] == 403
    user.is_authenticated = True
    user.roles = [SimpleNamespace(name="Admin")]
    routes_module = sys.modules[f"{route.ExpertRuleAPI.__module__.rsplit('.', 1)[0]}.route_expert_rule"]

    class InvalidService:
        def create(self, *_):
            raise routes_module.ExpertRuleValidationError("invalid")

    routes_module.ExpertRuleService = InvalidService
    session.rollback_calls = 0
    with app.test_request_context("/", method="POST", json={}):
        assert api.create_expert_rule()[0] == 400
    assert session.rollback_calls == 1

    csrf_route, _, _ = _load_route(monkeypatch, csrf_error=True, allowed_datasets={7})
    with app.test_request_context("/", method="POST", json={}):
        assert csrf_route.ExpertRuleAPI().create_expert_rule()[0] == 403


def test_discovery_serializes_rule_links_with_lifecycle_and_group_metadata(monkeypatch):
    app = Flask(__name__)
    route, _, session = _load_route(monkeypatch, allowed_datasets={7})
    revision = SimpleNamespace(
        id=1,
        rule_id=1,
        revision_number=2,
        lifecycle_version=3,
        status="approved",
        is_current=True,
        name="Final only",
        conditions=[],
        exceptions=[],
        examples=[],
    )
    stale = SimpleNamespace(
        id=2,
        rule_id=1,
        revision_number=3,
        lifecycle_version=4,
        status="approved",
        is_current=True,
        name="Stale",
        conditions=[],
        exceptions=[],
        examples=[],
    )
    denied = SimpleNamespace(
        id=3,
        rule_id=2,
        revision_number=1,
        lifecycle_version=1,
        status="approved",
        is_current=True,
        name="Denied",
        conditions=[],
        exceptions=[],
        examples=[],
    )
    rules = {
        1: SimpleNamespace(dataset_id=7, group=SimpleNamespace(id=5, name="Lọc bản ghi")),
        2: SimpleNamespace(dataset_id=8, group=None),
    }
    links = {
        1: [
            SimpleNamespace(kind="dataset", target_id=7, dataset_id=7, fingerprint="dataset"),
            SimpleNamespace(kind="glossary", target_id=3, dataset_id=7, fingerprint="glossary"),
        ],
        2: [SimpleNamespace(kind="dataset", target_id=7, dataset_id=7, fingerprint="old")],
        3: [SimpleNamespace(kind="dataset", target_id=8, dataset_id=8, fingerprint="dataset")],
    }
    session.query = lambda model: _Query(
        [revision, stale, denied] if model is route.ExpertRuleRevision else links.get(0, [])
    )

    def query(model):
        query_values = [revision, stale, denied] if model is route.ExpertRuleRevision else []
        result = _Query(query_values)
        if model is route.ExpertRuleLink:
            result.all = lambda: links.get(result.filters.get("revision_id"), [])
        return result

    session.query = query
    rule_model = sys.modules["text_to_bi.superset_semantic_layer.modules.expert_rule_management.models"].ExpertRule
    session.get = lambda model, key: rules[key] if model is rule_model else None
    api = route.ExpertRuleAPI()
    api._dataset = lambda dataset_id: SimpleNamespace(id=dataset_id)
    api._glossary = lambda _: [SimpleNamespace(dataset_id=7), SimpleNamespace(dataset_id=8)]
    api._fingerprint = lambda kind, _, __: {"dataset": "dataset", "glossary": "glossary"}[kind]
    with app.test_request_context("/", method="GET"):
        route_module = sys.modules[f"{route.ExpertRuleAPI.__module__.rsplit('.', 1)[0]}.route_expert_rule"]

        class DiscoverableService:
            def read_discoverable(self):
                return [(SimpleNamespace(dataset_id=7), revision, links[1])]

        route_module.ExpertRuleService = DiscoverableService
        route_module.serialize_discovered_rule = lambda *_: {
            "name": "Final only", "lifecycle_version": 3, "dataset_id": 7, "glossary_term_ids": [3],
            "metric_ids": [], "group": {"id": 5, "name": "Lọc bản ghi"},
        }
        status, body = api.read_discoverable_expert_rules()
    assert status == 200
    assert [item["name"] for item in body["result"]["rules"]] == ["Final only"]
    assert body["result"]["rules"][0]["lifecycle_version"] == 3
    # Discovery names what the rule links to, so a consumer can join it to catalog metrics and glossary terms.
    assert (
        body["result"]["rules"][0]["dataset_id"], body["result"]["rules"][0]["glossary_term_ids"],
        body["result"]["rules"][0]["metric_ids"],
    ) == (7, [3], [])
    # Rules of one group are alike, so a consumer can read them together.
    assert body["result"]["rules"][0]["group"] == {"id": 5, "name": "Lọc bản ghi"}


def test_serialized_rule_and_audit_expose_lifecycle_version(monkeypatch):
    app = Flask(__name__)
    route, _, session = _load_route(monkeypatch)
    revision = SimpleNamespace(
        rule_id=1,
        revision_number=2,
        lifecycle_version=3,
        status="approved",
        name="Final only",
        conditions=[],
        exceptions=[],
        examples=[],
    )
    event = SimpleNamespace(
        rule_id=1,
        event_type="approved",
        revision_number=2,
        lifecycle_version=3,
        actor_id=42,
        reason="Đã đối chiếu",
        occurred_at=datetime.now(timezone.utc),
    )
    session.query = lambda _: _Query([event])
    route_module = sys.modules[f"{route.ExpertRuleAPI.__module__.rsplit('.', 1)[0]}.route_expert_rule"]

    class ReadableRuleService:
        def read_rule_readable(self, _):
            return True

    class EventService:
        def read_history(self, _):
            return [event]

    route_module.ExpertRuleService = ReadableRuleService
    route_module.ExpertRuleEventService = EventService
    route_module.user_names = lambda: lambda user_id: "Bao Reviewer" if user_id == 42 else None
    api = route.ExpertRuleAPI()
    assert serialize_expert_rule(revision)["lifecycle_version"] == 3
    assert serialize_expert_rule(revision)["schema_version"] == 2
    with app.test_request_context("/", method="GET"):
        status, body = api.read_expert_rule_events(1)
    assert status == 200
    assert body["audit"] == [
        {
            "action": "approved",
            "revision": 2,
            "lifecycle_version": 3,
            "actor_id": 42,
            "actor_name": "Bao Reviewer",
            "reason": "Đã đối chiếu",
            "occurred_at": event.occurred_at.isoformat(),
        }
    ]


def test_a_name_collision_flushed_inside_the_service_is_refused_with_400(monkeypatch):
    app = Flask(__name__)
    route, _, session = _load_route(monkeypatch, allowed_datasets={7})
    collision = IntegrityError("INSERT INTO text_to_bi_expert_rule", {}, Exception("duplicate normalized_name"))
    route_module = sys.modules[f"{route.ExpertRuleAPI.__module__.rsplit('.', 1)[0]}.route_expert_rule"]

    class CollisionService:
        def create(self, *_):
            raise collision

    route_module.ExpertRuleService = CollisionService
    with app.test_request_context("/", method="POST", json={}):
        status, body = route.ExpertRuleAPI().create_expert_rule()
    assert (status, body) == (400, {"message": "Could not save the expert rule."})
    assert session.rollback_calls == 1 and session.commit_calls == 0


def test_self_approval_is_refused_with_403_and_rolled_back(monkeypatch):
    app = Flask(__name__)
    route, _, session = _load_route(monkeypatch)
    api = route.ExpertRuleAPI()
    route_module = sys.modules[f"{route.ExpertRuleAPI.__module__.rsplit('.', 1)[0]}.route_expert_rule"]
    received = {}

    def refuse(*_, require_second_reviewer):
        received["require_second_reviewer"] = require_second_reviewer
        raise ExpertRuleSelfApprovalError("Người soạn rule không thể tự duyệt")

    class SelfApprovalService:
        def require_current(self, _):
            return SimpleNamespace(rule_id=1)

        def approve(self, _rule_id, _expected_revision, _actor_id, _reason, require_second_reviewer):
            received["require_second_reviewer"] = require_second_reviewer
            raise ExpertRuleSelfApprovalError("self approval refused")

    route_module.ExpertRuleService = SelfApprovalService
    app.config["TEXT_TO_BI_REQUIRE_SECOND_REVIEWER"] = True
    with app.test_request_context("/", method="POST", json={"expected_revision": 1}):
        status, body = api.approve_expert_rule(1)
    assert received == {"require_second_reviewer": True}
    assert status == 403 and "self approval" in body["message"]
    assert session.rollback_calls == 1 and session.commit_calls == 0


def test_review_list_and_options_need_the_view_permission(monkeypatch):
    app = Flask(__name__)
    route, user, _ = _load_route(monkeypatch, permissions={"can_query"})
    user.roles = []
    api = route.ExpertRuleAPI()
    with app.test_request_context("/", method="GET"):
        assert api.read_expert_rules() == (403, {"message": SemanticLayerViewRequiredError.message})
        assert api.read_expert_rule_options()[0] == 403
        assert api.read_expert_rule_events(1)[0] == 403


def test_a_viewer_reads_the_review_list_but_only_rules_on_datasets_they_may_access(monkeypatch):
    app = Flask(__name__)
    route, user, _ = _load_route(monkeypatch, allowed_datasets={7}, permissions={"can_view"})
    user.roles = [SimpleNamespace(name="Semantic Layer Viewer")]
    revisions = [
        SimpleNamespace(id=1, rule_id=1, is_current=True),
        SimpleNamespace(id=2, rule_id=2, is_current=True),
    ]
    rules = {
        1: SimpleNamespace(id=1, dataset_id=7, group=None),
        2: SimpleNamespace(id=2, dataset_id=8, group=None),
    }
    datasets = {7: SimpleNamespace(id=7, table_name="allowed"), 8: SimpleNamespace(id=8, table_name="denied")}
    service = ExpertRuleService.__new__(ExpertRuleService)
    service.revisions = SimpleNamespace(read_all=lambda: revisions)
    service.rules = SimpleNamespace(
        read_all=lambda: list(rules.values()), read=lambda rule_id: rules.get(rule_id),
    )
    service.links = SimpleNamespace(read_for_revisions=lambda _: {})
    monkeypatch.setattr(expert_rule_service, "get_datasets", lambda _: list(datasets.values()))
    monkeypatch.setattr(expert_rule_service, "get_dataset", datasets.get)
    monkeypatch.setattr(expert_rule_service, "can_access_dataset", lambda dataset: dataset.id == 7)
    package = route.ExpertRuleAPI.__module__.rsplit(".", 1)[0]
    route_module = sys.modules[f"{package}.route_expert_rule"]
    route_module.ExpertRuleService = lambda: service
    route_module.ExpertRuleGroupService = lambda: SimpleNamespace(read_all=list)
    route_module.user_names = lambda: lambda _: None
    route_module.second_reviewer_required = lambda: False
    route_module.serialize_expert_rule_review_entry = lambda rule, *_: {
        "name": f"rule {rule.id}", "dataset_name": datasets[rule.dataset_id].table_name,
    }
    api = route.ExpertRuleAPI()

    with app.test_request_context("/", method="GET"):
        status, body = api.read_expert_rules()
        assert status == 200 and [rule["dataset_name"] for rule in body["rules"]] == ["allowed"]
        assert api.read_expert_rule_events(2) == (403, {"message": DatasetAccessError.message})
def test_discovery_needs_the_query_permission(monkeypatch):
    app = Flask(__name__)
    route, user, _ = _load_route(monkeypatch, allowed_datasets={7}, permissions={"can_view"})
    user.roles = []
    with app.test_request_context("/", method="GET"):
        assert route.ExpertRuleAPI().read_discoverable_expert_rules() == (
            403,
            {"message": SemanticLayerQueryRequiredError.message},
        )


def test_review_revisions_prefer_the_current_one_and_fall_back_to_the_latest(monkeypatch):
    revisions = [
        SimpleNamespace(rule_id=1, revision_number=1, is_current=False),
        SimpleNamespace(rule_id=1, revision_number=2, is_current=True),
        SimpleNamespace(rule_id=2, revision_number=1, is_current=False),
        SimpleNamespace(rule_id=2, revision_number=2, is_current=False),
    ]
    service = ExpertRuleService.__new__(ExpertRuleService)
    service.revisions = SimpleNamespace(read_all=lambda: revisions)
    service.rules = SimpleNamespace(read_all=lambda: [
        SimpleNamespace(id=1, dataset_id=7), SimpleNamespace(id=2, dataset_id=7),
    ])
    monkeypatch.setattr(expert_rule_service, "get_datasets", lambda _: [SimpleNamespace(id=7)])
    monkeypatch.setattr(expert_rule_service, "can_access_dataset", lambda _: True)

    chosen = service.read_for_review()
    assert [(revision.rule_id, revision.revision_number) for _, revision in chosen] == [(1, 2), (2, 2)]
def test_an_approved_rule_with_a_changed_link_is_outdated(monkeypatch):
    _load_route(monkeypatch)
    monkeypatch.setattr(
        rule_links, "live_fingerprint", lambda link: "dataset" if link.kind == "dataset" else "metric-changed",
    )
    approved = SimpleNamespace(status="approved", is_current=True)
    links = [
        SimpleNamespace(kind="dataset", target_id=7, dataset_id=7, fingerprint="dataset"),
        SimpleNamespace(kind="metric", target_id=9, dataset_id=7, fingerprint="metric-at-approval"),
    ]
    assert ExpertRuleService.review_state(approved, links) == "outdated"
    assert ExpertRuleService.review_state(approved, links[:1]) == "approved"
    assert ExpertRuleService.review_state(SimpleNamespace(status="draft", is_current=True), links) == "draft"


def test_a_rule_takes_its_metrics_from_its_glossary_terms(monkeypatch):
    _load_route(monkeypatch)
    term_links = {
        3: [SimpleNamespace(kind="metric", metric_id=17), SimpleNamespace(kind="column", metric_id=None)],
        4: [SimpleNamespace(kind="metric", metric_id=20), SimpleNamespace(kind="metric", metric_id=22)],
    }
    monkeypatch.setattr(
        rule_links, "_term_links", lambda term_id, dataset_id: term_links[term_id] if dataset_id == 12 else [],
    )
    monkeypatch.setattr(
        rule_links, "approved_metric",
        lambda metric_id: None if metric_id == 22 else SimpleNamespace(status="approved"),
    )

    payload = {"dataset_id": 12, "glossary_term_ids": [3, 4], "metric_ids": [99]}

    assert rule_links.with_term_metrics(payload) == {**payload, "metric_ids": [17, 20]}
    assert rule_links.with_term_metrics({"dataset_id": 12}) == {"dataset_id": 12}


def test_group_routes_are_admin_only_commit_once_and_answer_a_missing_group_with_404(monkeypatch):
    app = Flask(__name__)
    route, user, session = _load_route(monkeypatch)
    api = route.ExpertRuleAPI()
    package = route.ExpertRuleAPI.__module__.rsplit(".", 1)[0]
    group_routes = sys.modules[f"{package}.route_expert_rule_group"]
    expert_routes = sys.modules[f"{package}.route_expert_rule"]

    class GroupService:
        def delete(self, group_id, actor_id):
            assert (group_id, actor_id) == (5, 42)
            return [3, 4]

        def move_rule(self, *_):
            raise ExpertRuleGroupNotFoundError()

    group_routes.ExpertRuleGroupService = GroupService
    expert_routes.ExpertRuleGroupService = GroupService
    with app.test_request_context("/", method="DELETE"):
        assert api.delete_expert_rule_group(5) == (200, {"moved_rule_ids": [3, 4]})
    assert session.commit_calls == 1

    with app.test_request_context("/", method="PUT", json={"group_id": 404}):
        assert api.move_expert_rule(1)[0] == 404
    assert session.commit_calls == 1 and session.rollback_calls == 1

    user.roles = []
    with app.test_request_context("/", method="POST", json={"name": "Filters"}):
        assert api.create_expert_rule_group()[0] == 403


def test_group_suggestion_routes_are_admin_only_commit_once_and_refuse_a_bad_fingerprint(monkeypatch):
    app = Flask(__name__)
    route, user, session = _load_route(monkeypatch)
    api = route.ExpertRuleAPI()
    package = route.ExpertRuleAPI.__module__.rsplit(".", 1)[0]
    group_routes = sys.modules[f"{package}.route_expert_rule_group"]

    class GroupService:
        def apply_suggestion(self, payload, actor_id):
            assert (payload, actor_id) == ({"member_ids": [1, 2], "group_id": 4}, 42)
            return SimpleNamespace(id=4, name="Threshold", description=None), [1, 2]

        def suggest(self):
            return {}

        @staticmethod
        def dismiss_suggestion(_payload, _actor_id):
            raise ExpertRuleValidationError("Invalid suggestion fingerprint.")

    group_routes.ExpertRuleGroupService = GroupService
    with app.test_request_context("/", method="POST", json={"member_ids": [1, 2], "group_id": 4}):
        assert api.apply_expert_rule_group_suggestion() == (
            200,
            {"group": {"id": 4, "name": "Threshold", "description": None}, "moved_rule_ids": [1, 2]},
        )
    assert session.commit_calls == 1

    with app.test_request_context("/", method="POST", json={"fingerprint": "invalid"}):
        assert api.dismiss_expert_rule_group_suggestion()[0] == 400
    assert session.commit_calls == 1 and session.rollback_calls == 1

    user.roles = []
    with app.test_request_context("/", method="GET"):
        assert api.read_expert_rule_group_suggestions()[0] == 403
