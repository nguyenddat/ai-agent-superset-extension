"""Check the route security contract without importing the Superset runtime."""

import ast
import logging
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_SOURCE = ROOT / "extensions/semantic-layer/backend/src/text_to_bi/superset_semantic_layer"
ROUTE_FILES = sorted((SEMANTIC_SOURCE / "modules").glob("*/routes/*.py")) + [SEMANTIC_SOURCE / "registry.py"]
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
DECORATOR_ORDER = [
    "expose", "protect", "safe", "permission_name", "csrf_protected", "rollback_on_error", "handle_errors",
]


def decorator_name(decorator: ast.expr) -> str:
    value = decorator.func if isinstance(decorator, ast.Call) else decorator
    return value.id if isinstance(value, ast.Name) else value.attr if isinstance(value, ast.Attribute) else ""


def exposed_routes():
    for path in ROUTE_FILES:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = {
            target.id: statement.value.value
            for statement in module.body
            if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant)
            for target in statement.targets if isinstance(target, ast.Name)
        }
        for node in ast.walk(module):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            exposure = next(
                (decorator for decorator in node.decorator_list if decorator_name(decorator) == "expose"), None
            )
            if exposure is None:
                continue
            methods = {
                value.value for keyword in exposure.keywords if keyword.arg == "methods"
                for value in getattr(keyword.value, "elts", []) if isinstance(value, ast.Constant)
            }
            route_node = exposure.args[0] if exposure.args else None
            route = (
                route_node.value if isinstance(route_node, ast.Constant)
                else constants.get(route_node.id, node.name) if isinstance(route_node, ast.Name)
                else node.name
            )
            if isinstance(route_node, ast.JoinedStr):
                route = "".join(
                    part.value if isinstance(part, ast.Constant) else constants.get(part.value.id, "")
                    for part in route_node.values
                )
            yield path, node, route, methods or {"GET"}


ROUTES = list(exposed_routes())


@pytest.mark.parametrize(
    "path,node,route,methods", ROUTES, ids=lambda item: item.name if isinstance(item, Path) else None
)
def test_registered_routes_have_ordered_security_decorators(path, node, route, methods):
    names = [decorator_name(decorator) for decorator in node.decorator_list]
    required = {"expose", "protect", "safe", "permission_name", "handle_errors"}
    if methods & WRITE_METHODS:
        required.add("csrf_protected")
        if "preview" not in node.name and "validate" not in node.name:
            required.add("rollback_on_error")
    assert required <= set(names), f"{path}:{node.lineno} {route} {methods}: missing {required - set(names)}"
    ordered = [name for name in names if name in DECORATOR_ORDER]
    assert ordered == [name for name in DECORATOR_ORDER if name in names], f"{path}:{node.lineno} {route}: {ordered}"


@pytest.mark.parametrize(
    "path,node,route,methods", ROUTES, ids=lambda item: item.name if isinstance(item, Path) else None
)
def test_registered_routes_require_a_role_before_work(path, node, route, methods):
    if route == "/access":
        return
    calls = [
        child.func.id for child in ast.walk(node) if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    ]
    assert any(
        name in calls for name in ("require_admin", "require_semantic_layer_view", "require_semantic_layer_query")
    ), f"{path}:{node.lineno} {route} has no role gate"


@pytest.mark.parametrize(
    "path,node,route,methods", ROUTES, ids=lambda item: item.name if isinstance(item, Path) else None
)
def test_mutating_routes_check_role_before_request_parsing_or_writes(path, node, route, methods):
    if not methods & WRITE_METHODS:
        return
    gate_lines = [
        child.lineno
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id in {"require_admin", "require_semantic_layer_view", "require_semantic_layer_query"}
    ]
    assert gate_lines, f"{path}:{node.lineno} {route} has no role gate"
    side_effect_lines = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        function_name = (
            child.func.id if isinstance(child.func, ast.Name)
            else child.func.attr if isinstance(child.func, ast.Attribute)
            else ""
        )
        if function_name == "get_json" or function_name.startswith("ensure_") or function_name in {
            "add", "commit", "delete", "flush", "merge", "save", "create", "update", "approve", "reject"
        }:
            side_effect_lines.append(child.lineno)
    if side_effect_lines:
        assert min(gate_lines) < min(side_effect_lines), (
            f"{path}:{node.lineno} {route} reaches request parsing or mutation before its role gate"
        )


@pytest.mark.parametrize("role_name", ["Semantic Layer Viewer", "Semantic Layer Query", "Analyst"])
def test_valid_csrf_non_admin_cannot_reach_glossary_group_write(role_name):
    security_source = (SEMANTIC_SOURCE / "core/security.py").read_text(encoding="utf-8")
    security_module = ast.parse(security_source)
    security_functions = [
        node for node in security_module.body
        if isinstance(node, ast.FunctionDef) and node.name in {"is_admin", "require_admin", "csrf_protected"}
    ]
    events = []

    class AdminRequiredError(Exception):
        pass

    class CsrfTokenError(Exception):
        status = 400

    class ValidationError(Exception):
        pass

    request = SimpleNamespace(
        headers={"X-CSRFToken": "valid-token"},
        get_json=lambda silent: events.append("parse body"),
    )
    current_user = SimpleNamespace(is_authenticated=True, roles=[SimpleNamespace(name=role_name)])

    def validate_csrf(token):
        if token != "valid-token":
            raise ValidationError()

    security_namespace = {
        "wraps": wraps,
        "current_user": current_user,
        "request": request,
        "validate_csrf": validate_csrf,
        "ValidationError": ValidationError,
        "AdminRequiredError": AdminRequiredError,
        "CsrfTokenError": CsrfTokenError,
    }
    exec(  # noqa: S102
        compile(
            ast.Module(body=security_functions, type_ignores=[]), str(SEMANTIC_SOURCE / "core/security.py"), "exec"
        ),
        security_namespace,
    )

    group_source_path = SEMANTIC_SOURCE / "modules/glossary_management/routes/route_glossary_group.py"
    group_module = ast.parse(group_source_path.read_text(encoding="utf-8"))
    group_routes = next(
        node for node in group_module.body if isinstance(node, ast.ClassDef) and node.name == "GlossaryGroupRoutes"
    )
    route_method = next(
        node for node in group_routes.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_glossary_group"
    )
    route_method.decorator_list = []

    class GlossaryGroupService:
        def create(self, body):
            events.append("create group")

    class Route:
        def response(self, *args, **kwargs):
            events.append("respond")

    route_namespace = {
        "require_admin": security_namespace["require_admin"],
        "ensure_dictionary_tables": lambda: events.append("ensure tables"),
        "GlossaryGroupService": GlossaryGroupService,
        "request": request,
        "db": SimpleNamespace(session=SimpleNamespace(commit=lambda: events.append("commit"))),
        "serialize_glossary_group": lambda group: group,
    }
    exec(compile(ast.Module(body=[route_method], type_ignores=[]), str(group_source_path), "exec"), route_namespace)  # noqa: S102
    route = security_namespace["csrf_protected"](route_namespace["create_glossary_group"])
    with pytest.raises(AdminRequiredError):
        route(Route())
    assert events == []


def test_public_projection_routes_are_registered_with_query_role():
    expected = {
        "/datasets/query-metadata": "GET",
        "/relationships/approved": "GET",
        "/metrics/query-metadata": "GET",
        "/glossary/discovery": "GET",
        "/metric-candidates": "POST",
        "/dataset-drafts/validate": "POST",
        "/dataset-drafts/create": "POST",
    }
    for route, method in expected.items():
        matching = [(node, methods) for _, node, path, methods in ROUTES if path == route]
        assert matching and any(method in methods for _, methods in matching), f"missing {method} {route}"
        role = "require_admin" if route == "/dataset-drafts/create" else "require_semantic_layer_query"
        assert any(
            any(
                isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == role
                for child in ast.walk(node)
            )
            for node, _ in matching
        )


def test_core_security_uses_superset_dataset_authorization_and_csrf():
    source = (SEMANTIC_SOURCE / "core/security.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    functions = {
        node.name: ast.get_source_segment(source, node) for node in module.body if isinstance(node, ast.FunctionDef)
    }
    assert "security_manager.raise_for_access(datasource=dataset)" in functions["can_access_dataset"]
    assert "validate_csrf(request.headers.get(\"X-CSRFToken\"))" in functions["csrf_protected"]
    assert "can_access_dataset(dataset)" in functions["require_dataset_access"]


def test_public_projections_filter_dataset_access_and_relationship_endpoints():
    dictionary = (
        SEMANTIC_SOURCE / "modules/data_dictionary/services/srv_public_metadata.py"
    ).read_text(encoding="utf-8")
    metrics = (
        SEMANTIC_SOURCE / "modules/metric_management/services/srv_public_metadata.py"
    ).read_text(encoding="utf-8")
    assert "can_access_dataset(dataset)" in dictionary
    assert "contract.from_dataset_id not in visible_ids or contract.to_dataset_id not in visible_ids" in dictionary
    assert "referenced.dataset_id in visible_ids" in dictionary
    assert "can_access_dataset(dataset)" in metrics


def test_error_handlers_rollback_and_hide_unexpected_errors():
    source = (SEMANTIC_SOURCE / "core/database.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    functions = {
        node.name: ast.get_source_segment(source, node) for node in module.body if isinstance(node, ast.FunctionDef)
    }
    for name in ("handle_errors", "rollback_on_error"):
        assert "db.session.rollback()" in functions[name]
    assert 'self.response_500(message="Could not save the change.")' in functions["rollback_on_error"]


def test_error_wrappers_rollback_known_and_unexpected_failures():
    source = (SEMANTIC_SOURCE / "core/database.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    functions = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in {"handle_errors", "rollback_on_error"}
    ]
    rollbacks = []
    session = SimpleNamespace(rollback=lambda: rollbacks.append(True))
    namespace = {"wraps": wraps, "db": SimpleNamespace(session=session), "logger": logging.getLogger(__name__)}

    class SemanticLayerError(Exception):
        status = 409

    namespace["SemanticLayerError"] = SemanticLayerError
    exec(  # noqa: S102
        compile(ast.Module(body=functions, type_ignores=[]), str(SEMANTIC_SOURCE / "core/database.py"), "exec"),
        namespace,
    )

    class Response:
        def response(self, status, **body):
            return status, body

        def response_500(self, **body):
            return 500, body

    def known_failure(self):
        raise SemanticLayerError("safe conflict")

    def unexpected_failure(self):
        raise RuntimeError("sensitive detail")

    known_route = namespace["rollback_on_error"](namespace["handle_errors"](known_failure))
    assert known_route(Response()) == (409, {"message": "safe conflict"})
    assert len(rollbacks) == 1

    unexpected_route = namespace["rollback_on_error"](namespace["handle_errors"](unexpected_failure))
    assert unexpected_route(Response()) == (500, {"message": "Could not save the change."})
    assert len(rollbacks) == 2
