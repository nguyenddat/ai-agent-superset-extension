import logging
from typing import Any

from flask import Response, request, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset import db

from text_to_bi.superset_semantic_layer.common.exceptions import SemanticLayerError
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import (
    csrf_protected,
    require_admin,
    require_dataset_access,
    require_semantic_layer_view,
)
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.superset import requires_dataset

from ..services.srv_autofill import start_autofill
from ..services.srv_dictionary import DataDictionaryService
from ..utils.util_serializer import serialize_dictionary

logger = logging.getLogger(__name__)


class DataDictionaryRoutes(RouteMixin):
    # -------------------------READ---------------------------
    @expose("/datasets/reference-options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_reference_options(self):
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, datasets=DataDictionaryService().read_reference_options())

    @expose("/dataset/<int:dataset_id>/dictionary", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    @requires_dataset
    def get_dataset_dictionary(self, dataset: Any):
        require_semantic_layer_view()
        ensure_dictionary_tables()
        require_dataset_access(dataset)
        try:
            dictionary, columns = DataDictionaryService().read(dataset)
            return self.response(200, **serialize_dictionary(dataset, dictionary, columns))
        except Exception:
            logger.exception("Could not load dataset dictionary (dataset_id=%s)", dataset.id)
            db.session.rollback()
            return self.response_500(message="Could not load dataset dictionary.")

    # -------------------------UPDATE-------------------------
    @expose("/dataset/<int:dataset_id>/dictionary", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_dataset
    def update_dataset_dictionary(self, dataset: Any):
        require_admin()
        ensure_dictionary_tables()
        try:
            dictionary, columns = DataDictionaryService().update(dataset, request.get_json(silent=True))
            db.session.commit()
            return self.response(200, **serialize_dictionary(dataset, dictionary, columns))
        except SemanticLayerError:
            raise
        except Exception:
            logger.exception("Could not save dataset dictionary (dataset_id=%s)", dataset.id)
            db.session.rollback()
            return self.response_500(message="Could not save dataset dictionary.")

    @expose("/dataset/<int:dataset_id>/dictionary/suggest", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_dataset
    def suggest_dataset_dictionary(self, dataset: Any):
        require_admin()
        ensure_dictionary_tables()
        events = start_autofill(dataset)
        response = Response(
            stream_with_context(events), mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )
        response.call_on_close(events.close)
        return response
