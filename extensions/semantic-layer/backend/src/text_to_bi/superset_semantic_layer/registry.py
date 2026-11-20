from flask import abort, redirect
from flask_appbuilder import expose as expose_view
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import appbuilder
from superset.views.base import BaseSupersetView
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from .core.database import handle_errors
from .core.security import can_query_semantic_layer, can_view_semantic_layer, is_admin
from .migrations import ensure_dictionary_tables
from .modules.access_control.routes.access_control import AccessControlRoutes
from .modules.business_model.routes.business_model import BusinessModelRoutes
from .modules.data_dictionary.routes.route_dataset_draft import DatasetDraftRoutes
from .modules.data_dictionary.routes.route_dictionary import DataDictionaryRoutes
from .modules.data_dictionary.routes.route_dictionary_file import DataDictionaryFileRoutes
from .modules.data_dictionary.routes.route_grain import GrainRoutes
from .modules.data_dictionary.routes.route_public_metadata import DictionaryPublicRoutes
from .modules.data_dictionary.routes.route_relationship import RelationshipRoutes
from .modules.glossary_management.routes.route_contradiction import ContradictionRoutes
from .modules.glossary_management.routes.route_glossary_file import GlossaryFileRoutes
from .modules.glossary_management.routes.route_glossary_group import GlossaryGroupRoutes
from .modules.glossary_management.routes.route_glossary_term import GlossaryTermRoutes
from .modules.metric_management.routes.route_crud_metric_def import MetricDefinitionRoutes
from .modules.metric_management.routes.route_metric_candidate import MetricCandidateRoutes
from .modules.metric_management.routes.route_metric_contract import MetricContractRoutes
from .modules.metric_management.routes.route_public_metadata import MetricPublicRoutes


@api(
    id="text_to_bi_semantic_layer_api",
    name="Text to BI Semantic Layer API",
    description="Admin API for the Semantic Layer extension.",
    resource_name="semantic-layer",
)
class SemanticLayerAPI(
    DictionaryPublicRoutes,
    MetricPublicRoutes,
    MetricDefinitionRoutes,
    MetricContractRoutes,
    MetricCandidateRoutes,
    DatasetDraftRoutes,
    RelationshipRoutes,
    DataDictionaryRoutes,
    DataDictionaryFileRoutes,
    GrainRoutes,
    BusinessModelRoutes,
    GlossaryTermRoutes,
    GlossaryGroupRoutes,
    GlossaryFileRoutes,
    ContradictionRoutes,
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
        can_view = can_view_semantic_layer()
        if can_view:
            ensure_dictionary_tables()
        return self.response(200, is_admin=is_admin(), can_view=can_view, can_query=can_query_semantic_layer())


class SemanticLayerView(BaseSupersetView):
    route_base = "/semantic-layer"

    @expose_view("/")
    def page(self):
        if not getattr(current_user, "is_authenticated", False):
            return redirect(appbuilder.get_url_for_login)
        if not can_view_semantic_layer():
            abort(403)
        return self.render_app_template()


appbuilder.add_view_no_menu(SemanticLayerView)
