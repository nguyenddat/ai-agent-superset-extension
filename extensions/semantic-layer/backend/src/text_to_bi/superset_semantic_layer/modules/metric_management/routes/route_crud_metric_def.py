from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset import db

from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import csrf_protected, require_admin, require_semantic_layer_view
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.superset import requires_metric

from ..services.srv_metric_def import MetricDefService
from ..utils.util_serializer import serialize_metric_definition

prefix = "/dataset/<int:dataset_id>/metrics/<int:metric_id>"


class MetricDefinitionRoutes(RouteMixin):
    @expose(f"{prefix}/definition", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    @requires_metric
    def read_metric_definition(self, dataset: Any, metric: Any):
        require_semantic_layer_view()
        ensure_dictionary_tables()
        definition = MetricDefService().read(dataset, metric)
        return self.response(200, definition=serialize_metric_definition(definition))

    @expose(f"{prefix}/definition", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_metric
    def update_metric_definition(self, dataset: Any, metric: Any):
        require_admin()
        ensure_dictionary_tables()
        definition = MetricDefService().update(dataset, metric, request.get_json(silent=True))
        db.session.commit()
        return self.response(200, definition=serialize_metric_definition(definition))

    @expose(f"{prefix}/query-defaults", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_metric
    def update_metric_query_defaults(self, dataset: Any, metric: Any):
        """Đặt grain, mốc thời gian và bộ lọc mặc định của metric; trả về giá trị đã chuẩn hóa."""
        require_admin()
        ensure_dictionary_tables()
        defaults = MetricDefService().update_query_defaults(dataset, metric, request.get_json(silent=True))
        db.session.commit()
        return self.response(200, query_defaults=None if defaults.is_empty() else defaults.as_dict())

    # -------------------------DELETE-------------------------
    @expose(f"{prefix}/definition", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_metric
    def delete_metric_definition(self, dataset: Any, metric: Any):
        require_admin()
        ensure_dictionary_tables()
        MetricDefService().delete(dataset, metric)
        db.session.commit()
        return self.response(200, message="Đã xóa định nghĩa nghiệp vụ.")
