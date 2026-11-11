from flask_appbuilder.api import expose, permission_name, protect, safe
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ....core.database import handle_errors
from ....core.security import can_query_semantic_layer, is_admin, require_semantic_layer_view
from ....migrations import ensure_dictionary_tables
from ...access_control.routes.access_control import AccessControlRoutes
from ...agent_ladder.routes.agent import AgentLadderRoutes
from ...business_model.routes.business_model import BusinessModelRoutes
from ...data_dictionary.routes.dictionary import DataDictionaryRoutes
from ...glossary.routes.glossary import GlossaryRoutes
from ...semantic_query.routes.consumer import ConsumerRoutes
from ...semantic_query.routes.metrics import MetricContractRoutes
from ...semantic_query.routes.relationships import RelationshipRoutes


@api(
    id="text_to_bi_semantic_layer_api",
    name="Text to BI Semantic Layer API",
    description="Admin API for the Semantic Layer extension.",
    resource_name="semantic-layer",
)
class SemanticLayerAPI(
    MetricContractRoutes,
    ConsumerRoutes,
    AgentLadderRoutes,
    RelationshipRoutes,
    DataDictionaryRoutes,
    BusinessModelRoutes,
    GlossaryRoutes,
    AccessControlRoutes,
    RestApi,
):
    openapi_spec_tag = "Text to BI Semantic Layer"
    class_permission_name = "text_to_bi_semantic_layer_api"

    @expose("/access", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_access(self):
        """What the signed-in user may do in the Semantic Layer; 403 when they may not even view it."""
        require_semantic_layer_view()
        ensure_dictionary_tables()
        return self.response(200, is_admin=is_admin(), can_view=True, can_query=can_query_semantic_layer())
