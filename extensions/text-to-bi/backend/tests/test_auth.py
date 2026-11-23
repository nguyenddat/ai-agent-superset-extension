import sys
from types import ModuleType

import pytest
from support import ADMIN, EDITOR, QUERY, VIEWER, call_route
from werkzeug.exceptions import Forbidden
from wtforms import ValidationError

from text_to_bi.superset_text_to_bi.modules.auth.exceptions import (
    AdminRequiredError,
    EditRequiredError,
    QueryRequiredError,
    ViewRequiredError,
)
from text_to_bi.superset_text_to_bi.modules.auth.routes.route_auth import AuthAPI
from text_to_bi.superset_text_to_bi.modules.auth.services import srv_access
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_roles import ensure_text_to_bi_roles

VIEW = ("can_view", "Text to BI")
EDIT = ("can_edit", "Text to BI")
QUERY_DATA = ("can_query", "Text to BI")
API_READ = ("can_read", "text_to_bi_api")
API_WRITE = ("can_write", "text_to_bi_api")


def role_permissions(env, name):
    return set(env.security_manager.find_role(name).permissions)


def test_bootstrap_creates_the_three_roles_and_keeps_the_view_menu_admin_only(env):
    assert role_permissions(env, VIEWER) == {VIEW, API_READ}
    assert role_permissions(env, EDITOR) == {VIEW, EDIT, API_READ, API_WRITE}
    assert role_permissions(env, QUERY) == {QUERY_DATA, API_READ, API_WRITE}
    assert {VIEW, EDIT, QUERY_DATA} <= role_permissions(env, ADMIN)
    assert "Text to BI" in env.security_manager.ADMIN_ONLY_VIEW_MENUS
    assert "Security" in env.security_manager.ADMIN_ONLY_VIEW_MENUS


def test_bootstrap_takes_the_view_menu_back_from_built_in_roles_and_is_idempotent(env):
    alpha = env.security_manager.find_role("Alpha")
    env.security_manager.add_permission_role(alpha, VIEW)
    env.security_manager.add_permission_role(alpha, API_READ)

    ensure_text_to_bi_roles()
    ensure_text_to_bi_roles()

    assert role_permissions(env, "Alpha") == {API_READ}
    assert role_permissions(env, EDITOR) == {VIEW, EDIT, API_READ, API_WRITE}
    assert len(env.security_manager.find_role(EDITOR).permissions) == 4


@pytest.mark.parametrize(("roles", "expected"), [
    ((ADMIN,), (True, True, True, True)),
    ((VIEWER,), (False, True, False, False)),
    ((EDITOR,), (False, True, True, False)),
    ((QUERY,), (False, False, False, True)),
    (("Gamma",), (False, False, False, False)),
])
def test_me_tells_the_page_what_the_user_may_do(env, roles, expected):
    env.sign_in(env.add_user(2, "lan", *roles))

    me = call_route(env.app, AuthAPI.get_me).json

    assert (me["user_id"], me["username"], me["name"]) == (2, "lan", "Lan Tester")
    assert (me["is_admin"], me["can_view"], me["can_edit"], me["can_query"]) == expected


def test_admin_lists_every_active_user_with_their_roles(env):
    env.add_user(2, "lan", VIEWER, "Gamma")

    assignments = call_route(env.app, AuthAPI.list_role_assignments).json

    assert [role["name"] for role in assignments["roles"]] == [VIEWER, EDITOR, QUERY]
    assert all(role["description"] for role in assignments["roles"])
    users = {user["username"]: user for user in assignments["users"]}
    assert (users["admin"]["is_admin"], users["admin"]["roles"]) == (True, [])
    assert (users["lan"]["roles"], users["lan"]["other_roles"]) == ([VIEWER], ["Gamma"])


def test_admin_replaces_only_the_text_to_bi_roles(env):
    lan = env.add_user(2, "lan", VIEWER, "Gamma")

    response = call_route(env.app, AuthAPI.update_role_assignment, "PUT", {"roles": [EDITOR, QUERY, EDITOR]}, user_id=2)

    assert response.status == 200
    assert (response.json["roles"], response.json["other_roles"]) == ([EDITOR, QUERY], ["Gamma"])
    assert [role.name for role in lan.roles] == ["Gamma", EDITOR, QUERY]
    cleared = call_route(env.app, AuthAPI.update_role_assignment, "PUT", {"roles": []}, user_id=2).json
    assert (cleared["roles"], cleared["other_roles"]) == ([], ["Gamma"])


@pytest.mark.parametrize(("body", "user_id", "status", "code"), [
    ({"roles": ["Admin"]}, 2, 422, "invalid_role_assignment"),
    ({"roles": [VIEWER], "extra": 1}, 2, 422, "invalid_request"),
    ({"roles": [VIEWER]}, 99, 404, "user_not_found"),
])
def test_role_assignment_rejects_bad_requests(env, body, user_id, status, code):
    env.add_user(2, "lan", VIEWER)

    response = call_route(env.app, AuthAPI.update_role_assignment, "PUT", body, user_id=user_id)

    assert (response.status, response.json["code"]) == (status, code)


def test_only_an_admin_manages_role_assignments(env):
    env.sign_in(env.add_user(2, "lan", EDITOR))

    listing = call_route(env.app, AuthAPI.list_role_assignments)
    update = call_route(env.app, AuthAPI.update_role_assignment, "PUT", {"roles": [EDITOR]}, user_id=2)

    assert (listing.status, listing.json["code"]) == (403, "admin_required")
    assert (update.status, update.json["code"]) == (403, "admin_required")


def test_role_assignment_needs_a_csrf_token(env, monkeypatch):
    from text_to_bi.superset_text_to_bi.core import security

    def reject(token):
        raise ValidationError("bad token")

    monkeypatch.setattr(security, "validate_csrf", reject)
    env.add_user(2, "lan")

    response = call_route(env.app, AuthAPI.update_role_assignment, "PUT", {"roles": [VIEWER]}, user_id=2)

    assert (response.status, response.json["code"]) == (403, "csrf_token_invalid")


def test_access_helpers_follow_the_roles(env):
    env.sign_in(env.add_user(2, "lan", VIEWER))
    with env.app.test_request_context():
        srv_access.require_view()
        with pytest.raises(EditRequiredError):
            srv_access.require_edit(None)
        with pytest.raises(QueryRequiredError):
            srv_access.require_query(None)
        with pytest.raises(AdminRequiredError):
            srv_access.require_admin()
        env.catalog.current_user = None
        with pytest.raises(ViewRequiredError):
            srv_access.require_view()


def test_the_page_needs_view_or_query_access(env, monkeypatch):
    # The metric module reads Superset's SqlMetric, which the local stub of Superset does not have.
    for name in ("superset.connectors", "superset.connectors.sqla"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    models = ModuleType("superset.connectors.sqla.models")
    models.SqlMetric = type("SqlMetric", (), {})
    monkeypatch.setitem(sys.modules, models.__name__, models)
    from text_to_bi.superset_text_to_bi.entrypoint import TextToBIView

    view = TextToBIView()
    with env.app.test_request_context():
        assert view.page() == "app"
        env.sign_in(env.add_user(2, "minh", QUERY))
        assert view.page() == "app"
        env.sign_in(env.add_user(3, "hoa", "Gamma"))
        with pytest.raises(Forbidden):
            view.page()
        env.catalog.current_user = None
        assert view.page().location == "/login/"
