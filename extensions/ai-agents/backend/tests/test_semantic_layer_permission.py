import importlib
import sys
import types
from types import SimpleNamespace

import pytest

from text_to_bi.superset_ai_agent.core.exceptions import SemanticLayerQueryRequiredError

SECURITY_MODULE = "text_to_bi.superset_ai_agent.core.security"


@pytest.fixture
def security(monkeypatch):
    """core.security with a signed-in user whose roles grant the permissions in `granted`."""
    user = SimpleNamespace(is_authenticated=True, roles=[], granted=set())
    login_module = types.ModuleType("flask_login")
    login_module.current_user = user
    superset_module = types.ModuleType("superset")
    superset_module.security_manager = SimpleNamespace(
        can_access=lambda permission, view_menu: (permission, view_menu) in user.granted
    )
    monkeypatch.setitem(sys.modules, "flask_login", login_module)
    monkeypatch.setitem(sys.modules, "superset", superset_module)
    monkeypatch.delitem(sys.modules, SECURITY_MODULE, raising=False)
    module = importlib.import_module(SECURITY_MODULE)
    return SimpleNamespace(module=module, user=user)


def test_asking_the_agent_needs_the_semantic_layer_query_permission(security):
    with pytest.raises(SemanticLayerQueryRequiredError, match="Semantic Layer Query"):
        security.module.require_semantic_layer_query()
    security.user.granted = {("can_view", "Text to BI Semantic Layer")}
    assert security.module.can_query_semantic_layer() is False
    security.user.granted = {("can_query", "Text to BI Semantic Layer")}
    assert security.module.can_query_semantic_layer() is True


def test_an_administrator_may_always_ask(security):
    security.user.roles = [SimpleNamespace(name="Admin")]
    assert security.module.can_query_semantic_layer() is True
    security.user.roles, security.user.is_authenticated = [], False
    security.user.granted = {("can_query", "Text to BI Semantic Layer")}
    assert security.module.can_query_semantic_layer() is False
