from .modules.access_control.services.roles import declare_semantic_layer_admin_only
from .modules.catalog.routes.semantic_layer import SemanticLayerAPI  # noqa: F401
from .modules.catalog.routes.view import SemanticLayerView  # noqa: F401
from .modules.expert_rules.routes.expert_rules import ExpertRuleAPI  # noqa: F401

# Declared on load, so `superset init` in this process never hands the Semantic Layer permissions to Alpha or Gamma.
declare_semantic_layer_admin_only()
