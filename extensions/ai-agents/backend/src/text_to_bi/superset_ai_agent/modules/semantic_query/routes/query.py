from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_ai_agent.common.public import public_payload
from text_to_bi.superset_ai_agent.core.database import handle_errors
from text_to_bi.superset_ai_agent.core.security import require_semantic_layer_query

from ..exceptions import QueryDatabaseIdRequiredError
from ..services.catalog import read_catalog
from ..services.dimensions import read_dimension_members
from ..services.graph import read_schema_graph
from ..services.sources import read_sources


@api(id="text_to_bi_agent_semantic_query_api", name="AI Agent semantic queries", resource_name="semantic-query")
class AgentSemanticQueryAPI(RestApi):
    class_permission_name = "text_to_bi_chat_api"

    @expose("/semantic-catalog", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def semantic_catalog(self):
        require_semantic_layer_query()
        return self.response(200, **public_payload(read_catalog(request.headers.get("Cookie", ""))))

    @expose("/schema-graph", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def schema_graph(self):
        require_semantic_layer_query()
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            raise QueryDatabaseIdRequiredError()
        return self.response(200, **public_payload(read_schema_graph(database_id, request.headers.get("Cookie", ""))))

    @expose("/dataset/<int:dataset_id>/dimension-members", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def dimension_members(self, dataset_id: int):
        require_semantic_layer_query()
        return self.response(200, **public_payload(read_dimension_members(dataset_id, request.headers.get("Cookie", ""))))

    @expose("/data-model/sources", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def data_model_sources(self):
        require_semantic_layer_query()
        return self.response(200, **public_payload(read_sources(request.headers.get("Cookie", ""))))
