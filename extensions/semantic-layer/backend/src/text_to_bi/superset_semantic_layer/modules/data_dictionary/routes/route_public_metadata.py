from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe

from text_to_bi.superset_semantic_layer.common.public import public_payload
from text_to_bi.superset_semantic_layer.core.database import handle_errors
from text_to_bi.superset_semantic_layer.core.exceptions import DatabaseIdRequiredError
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import require_semantic_layer_query
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables

from ..services.srv_public_metadata import read_approved_relationships, read_query_metadata


class DictionaryPublicRoutes(RouteMixin):
    @expose("/datasets/query-metadata", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_public_dictionary(self):
        require_semantic_layer_query()
        database_id = request.args.get("database_id", type=int)
        if "database_id" in request.args and database_id is None:
            raise DatabaseIdRequiredError()
        ensure_dictionary_tables()
        return self.response(200, **public_payload(read_query_metadata(database_id)))

    @expose("/relationships/approved", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_public_relationships(self):
        require_semantic_layer_query()
        ensure_dictionary_tables()
        return self.response(200, **public_payload(read_approved_relationships()))
