from .modules.access_control.services.roles import declare_semantic_layer_admin_only
from .modules.expert_rule_management.routes.route_expert_rule_api import ExpertRuleAPI  # noqa: F401
from .registry import (
    SemanticLayerAPI,  # noqa: F401
    SemanticLayerView,  # noqa: F401
)

# Declared on load, so `superset init` in this process never hands the Semantic Layer permissions to Alpha or Gamma.
declare_semantic_layer_admin_only()
