from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe

from text_to_bi.superset_semantic_layer.core.database import handle_errors
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import require_admin
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.superset import requires_dataset

from ..services.srv_grain import read_grain_profile


class GrainRoutes(RouteMixin):
    # -------------------------READ---------------------------
    @expose("/dataset/<int:dataset_id>/grain-profile", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    @requires_dataset
    def get_grain_profile(self, dataset: Any):
        require_admin()
        ensure_dictionary_tables()
        profile = read_grain_profile(
            dataset,
            request.args.get("time_column") or None,
            request.args.get("row_kind_column") or None,
            request.args.get("temporal_kind") or None,
        )
        if profile is None:
            return self.response_500(message="Could not read the grain profile.")
        return self.response(200, **profile)
