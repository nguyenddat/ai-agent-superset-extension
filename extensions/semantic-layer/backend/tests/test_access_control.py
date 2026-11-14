import ast
import importlib
import sys
import types
from types import SimpleNamespace

import pytest
from catalog_source import api_class, api_methods, compile_into

from text_to_bi.superset_semantic_layer.core.exceptions import (
    AdminRequiredError,
    SemanticLayerQueryRequiredError,
    SemanticLayerViewRequiredError,
)
from text_to_bi.superset_semantic_layer.modules.access_control.exceptions import RoleAssignmentError

PACKAGE = "text_to_bi.superset_semantic_layer"
VIEW = ("can_view", "Text to BI Semantic Layer")
QUERY = ("can_query", "Text to BI Semantic Layer")


class _Role:
    def __init__(self, name, permissions=()):
        self.name = name
        self.permissions = list(permissions)


class _SecurityManager:
    """Flask-AppBuilder's role calls on in-memory roles; a permission view is its (permission, view menu) pair."""

    ADMIN_ONLY_VIEW_MENUS = frozenset({"Security"})

    def __init__(self, current_user):
        self.current_user = current_user
        self.roles = {name: _Role(name) for name in ("Admin", "Alpha", "Gamma")}
        self.permission_views = {}

    def add_role(self, name):
        return self.roles.setdefault(name, _Role(name))

    def find_role(self, name):
        return self.roles.get(name)

    def add_permission_view_menu(self, permission_name, view_menu_name):
        return self.permission_views.setdefault((permission_name, view_menu_name), (permission_name, view_menu_name))

    def find_permission_view_menu(self, permission_name, view_menu_name):
        return self.permission_views.get((permission_name, view_menu_name))

    def add_permission_role(self, role, permission_view):
        if permission_view not in role.permissions:
            role.permissions.append(permission_view)

    def del_permission_role(self, role, permission_view):
        if permission_view in role.permissions:
            role.permissions.remove(permission_view)

    def can_access(self, permission_name, view_menu_name):
        return any((permission_name, view_menu_name) in role.permissions for role in self.current_user.roles)


@pytest.fixture
def access(monkeypatch):
    """core.security and the access_control services, imported against a fake Superset security manager."""
    current_user = SimpleNamespace(id=1, is_authenticated=True, roles=[])
    security_manager = _SecurityManager(current_user)
    superset_module = types.ModuleType("superset")
    superset_module.security_manager = security_manager
    superset_module.db = SimpleNamespace(session=None)
    exceptions_module = types.ModuleType("superset.exceptions")
    exceptions_module.SupersetSecurityException = type("SupersetSecurityException", (Exception,), {})
    login_module = types.ModuleType("flask_login")
    login_module.current_user = current_user
    for name, module in {"superset": superset_module, "superset.exceptions": exceptions_module}.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "flask_login", login_module)
    names = ("core.security", "modules.superset.services.srv_role", "modules.access_control.services.roles")
    for name in names:
        monkeypatch.delitem(sys.modules, f"{PACKAGE}.{name}", raising=False)
    security, _, roles = (importlib.import_module(f"{PACKAGE}.{name}") for name in names)
    return SimpleNamespace(security=security, roles=roles, manager=security_manager, user=current_user)


def test_the_roles_are_created_with_their_permissions_once_and_kept_from_built_in_roles(access):
    gamma = access.manager.roles["Gamma"]
    gamma.permissions = [VIEW, QUERY, ("can_read", "Dashboard")]
    access.roles.ensure_semantic_layer_roles()
    access.roles.ensure_semantic_layer_roles()

    viewer = access.manager.roles["Semantic Layer Viewer"]
    query = access.manager.roles["Semantic Layer Query"]
    assert viewer.permissions == [
        VIEW, ("can_read", "text_to_bi_semantic_layer_api"), ("can_read", "text_to_bi_expert_rule_api"),
    ]
    assert query.permissions == [
        QUERY,
        ("can_read", "text_to_bi_semantic_layer_api"),
        ("can_read", "text_to_bi_expert_rule_api"),
        ("can_read", "text_to_bi_chat_api"),
        ("can_write", "text_to_bi_chat_api"),
    ]
    assert access.manager.roles["Admin"].permissions == [VIEW, QUERY]
    assert gamma.permissions == [("can_read", "Dashboard")]
    # Superset's role sync now treats the view menu as admin-only, so `superset init` never grants it to Gamma.
    assert access.manager.ADMIN_ONLY_VIEW_MENUS == {"Security", "Text to BI Semantic Layer"}


@pytest.mark.parametrize(
    ("role_names", "can_view", "can_query"),
    [
        ((), False, False),
        (("Gamma",), False, False),
        (("Gamma", "Semantic Layer Viewer"), True, False),
        (("Gamma", "Semantic Layer Query"), False, True),
        (("Semantic Layer Viewer", "Semantic Layer Query"), True, True),
        (("Admin",), True, True),
    ],
)
def test_each_role_grants_its_own_capability(access, role_names, can_view, can_query):
    access.roles.ensure_semantic_layer_roles()
    access.user.roles = [access.manager.roles[name] for name in role_names]
    access.manager.roles["Admin"].permissions = []  # Admin passes by its role name, as require_admin does.
    assert access.security.can_view_semantic_layer() is can_view
    assert access.security.can_query_semantic_layer() is can_query


def test_the_role_descriptions_name_only_what_each_role_opens(access):
    viewer = access.roles.SEMANTIC_LAYER_ROLES["Semantic Layer Viewer"]["description"]
    query = access.roles.SEMANTIC_LAYER_ROLES["Semantic Layer Query"]["description"]
    # A Viewer reads Metrics, Business Glossary and Expert Rules only; the Data Dictionary stays an administrator's.
    assert "Metrics, Business Glossary và Expert Rules" in viewer and "Data Dictionary" not in viewer
    # The page, and so its "Chạy thử" button, needs the Viewer role as well.
    assert "AI Agent" in query and "cần thêm nhóm Viewer" in query


def test_the_checks_answer_403_with_the_role_to_ask_for(access):
    access.user.roles = []
    with pytest.raises(SemanticLayerViewRequiredError, match="Semantic Layer Viewer"):
        access.security.require_semantic_layer_view()
    with pytest.raises(SemanticLayerQueryRequiredError, match="Semantic Layer Query"):
        access.security.require_semantic_layer_query()
    access.user.is_authenticated = False
    access.user.roles = [_Role("Semantic Layer Viewer", [VIEW])]
    assert access.security.can_view_semantic_layer() is False


def test_assigning_roles_replaces_only_the_semantic_layer_roles(access):
    access.roles.ensure_semantic_layer_roles()
    gamma, viewer = access.manager.roles["Gamma"], access.manager.roles["Semantic Layer Viewer"]
    user = SimpleNamespace(id=5, username="lan", get_full_name=lambda: " ", roles=[gamma, viewer])
    access.roles.assign_semantic_layer_roles(user, ["Semantic Layer Query"])
    assert [role.name for role in user.roles] == ["Gamma", "Semantic Layer Query"]
    assert access.roles.role_assignment(user) == {
        "id": 5,
        "username": "lan",
        "name": "lan",
        "is_admin": False,
        "roles": ["Semantic Layer Query"],
        "other_roles": ["Gamma"],
    }
    access.roles.assign_semantic_layer_roles(user, [])
    assert [role.name for role in user.roles] == ["Gamma"]


@pytest.mark.parametrize("body", [None, [], {}, {"roles": "Semantic Layer Viewer"}, {"roles": ["Admin"]}])
def test_only_semantic_layer_role_names_may_be_assigned(access, body):
    with pytest.raises(RoleAssignmentError):
        access.roles.requested_role_names(body)


def test_a_role_list_is_read_without_duplicates(access):
    body = {"roles": ["Semantic Layer Query", "Semantic Layer Viewer", "Semantic Layer Query"]}
    assert access.roles.requested_role_names(body) == ["Semantic Layer Query", "Semantic Layer Viewer"]


class _ResponseAPI:
    def response(self, status, **payload):
        return status, payload


def _assignment_api(body, *, admin=True):
    commits = []
    user = SimpleNamespace(id=5, roles=[])

    def require_admin():
        if not admin:
            raise AdminRequiredError()

    def assign(target, role_names):
        target.roles = role_names

    def requested_role_names(payload):
        if not isinstance(payload, dict):
            raise RoleAssignmentError()
        return payload["roles"]

    namespace = {
        "RestApi": _ResponseAPI,
        "require_admin": require_admin,
        "ensure_dictionary_tables": lambda: None,
        "request": SimpleNamespace(get_json=lambda silent=True: body),
        "db": SimpleNamespace(session=SimpleNamespace(commit=lambda: commits.append(True), rollback=lambda: None)),
        "active_users": lambda: [user],
        "require_user": lambda user_id: user,
        "semantic_layer_role_options": lambda: [{"name": "Semantic Layer Viewer", "description": "Xem"}],
        "role_assignment": lambda target: {"id": target.id, "roles": target.roles},
        "requested_role_names": requested_role_names,
        "assign_semantic_layer_roles": assign,
    }
    compile_into(namespace, api_class({"list_role_assignments", "update_role_assignment"}))
    return namespace["SemanticLayerAPI"](), commits


def test_only_an_administrator_lists_or_assigns_roles():
    api, commits = _assignment_api({"roles": []}, admin=False)
    assert api.list_role_assignments() == (403, {"message": "Admin access required."})
    assert api.update_role_assignment(5) == (403, {"message": "Admin access required."})
    assert commits == []


def test_the_assignment_screen_reads_roles_and_users_and_saves_a_user_roles():
    api, commits = _assignment_api({"roles": ["Semantic Layer Viewer"]})
    status, payload = api.list_role_assignments()
    assert status == 200 and payload["roles"][0]["name"] == "Semantic Layer Viewer"
    assert payload["users"] == [{"id": 5, "roles": []}]
    assert api.update_role_assignment(5) == (200, {"user": {"id": 5, "roles": ["Semantic Layer Viewer"]}})
    assert commits == [True]


def test_an_invalid_role_list_is_refused_without_saving():
    api, commits = _assignment_api(None)
    assert api.update_role_assignment(5) == (400, {"message": RoleAssignmentError.message})
    assert commits == []


@pytest.mark.parametrize(("can_view", "can_query"), [(False, False), (False, True), (True, False)])
def test_the_access_probe_answers_200_even_without_the_view_permission(can_view, can_query):
    tables = []
    namespace = {
        "RestApi": _ResponseAPI,
        "is_admin": lambda: False,
        "can_view_semantic_layer": lambda: can_view,
        "can_query_semantic_layer": lambda: can_query,
        "ensure_dictionary_tables": lambda: tables.append(True),
    }
    compile_into(namespace, api_class({"get_access"}))
    assert namespace["SemanticLayerAPI"]().get_access() == (
        200, {"is_admin": False, "can_view": can_view, "can_query": can_query}
    )
    # Only a viewer opens the page, so only a viewer's probe prepares its tables.
    assert tables == ([True] if can_view else [])


def test_assignment_routes_follow_the_route_conventions():
    methods = api_methods()
    expected_decorators = {
        "list_role_assignments": ["expose('/role-assignments', methods=('GET',))", "protect()", "safe", "permission_name('read')", "handle_errors"],
        "update_role_assignment": [
            "expose('/role-assignments/<int:user_id>', methods=('PUT',))", "protect()", "safe", "permission_name('write')", "csrf_protected", "rollback_on_error", "handle_errors"
        ],
    }
    for name, decorators_expected in expected_decorators.items():
        source = ast.unparse(methods[name])
        decorators = [ast.unparse(item) for item in methods[name].decorator_list]
        assert decorators == decorators_expected
        assert "require_admin()" in source
