"""Register the Text to BI backend APIs with Superset."""

from .modules.auth.routes.route_auth import AuthAPI  # noqa: F401
from .modules.auth.services.srv_roles import declare_text_to_bi_admin_only
from .modules.data_dictionary.routes.route_data_dictionary import DataDictionaryAPI  # noqa: F401
from .modules.data_lineage.routes.route_data_lineage import DataLineageAPI  # noqa: F401
from .modules.expert_rule_management.routes.route_expert_rule import TextToBIExpertRuleAPI  # noqa: F401
from .modules.glossary_management.routes.route_glossary import TextToBIGlossaryAPI  # noqa: F401
from .modules.metric_management.routes.route_metric import TextToBIMetricAPI  # noqa: F401

# Superset's role synchronization must not grant these extension permissions to default roles.
declare_text_to_bi_admin_only()
