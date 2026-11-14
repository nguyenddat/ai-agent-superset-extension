from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from .route_expert_rule import ExpertRuleRoutes
from .route_expert_rule_file import ExpertRuleFileRoutes
from .route_expert_rule_group import ExpertRuleGroupRoutes


@api(id="text_to_bi_expert_rule_api", name="Text to BI Expert Rules", resource_name="expert-rules")
class ExpertRuleAPI(ExpertRuleRoutes, ExpertRuleGroupRoutes, ExpertRuleFileRoutes, RestApi):
    class_permission_name = "text_to_bi_expert_rule_api"
