from uuid import UUID

from flask_appbuilder.api import expose, permission_name, protect, safe
from superset.extensions import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_text_to_bi.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION, OPENAPI_TAG
from text_to_bi.superset_text_to_bi.core.security import csrf_protected
from text_to_bi.superset_text_to_bi.core.validation import request_body
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import require_view
from text_to_bi.superset_text_to_bi.modules.management_payload import json_payload

from ..dependencies import metric_service
from ..exceptions import MetricValidationError
from ..migrations import ensure_metric_tables
from ..schemas.schema_metric import MetricCreate, MetricPatch


def metric_id_from_path(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise MetricValidationError("ID metric không hợp lệ.") from error


@api(
    id="text_to_bi_metric_api", name="Text to BI metric API",
    description="Manages manual metrics and reads Superset metrics directly.", resource_name="metrics",
)
class TextToBIMetricAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    @expose("/datasets/<int:dataset_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_metrics(self, dataset_id: int):
        require_view()
        ensure_metric_tables()
        return self.response(200, metrics=json_payload(metric_service().list_metrics(dataset_id)))

    @expose("/<metric_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_metric(self, metric_id: str):
        require_view()
        ensure_metric_tables()
        metric = metric_service().get_metric(metric_id_from_path(metric_id))
        return self.response(200, metric=json_payload(metric))

    @expose("/", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_metric(self):
        body = request_body(MetricCreate)
        ensure_metric_tables()
        metric = metric_service().create_metric(body.model_dump())
        db.session.commit()
        return self.response(201, metric=json_payload(metric))

    @expose("/<metric_id>", methods=("PATCH",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_metric(self, metric_id: str):
        body = request_body(MetricPatch)
        ensure_metric_tables()
        metric = metric_service().update_metric(
            metric_id_from_path(metric_id), body.model_dump(exclude_unset=True)
        )
        db.session.commit()
        return self.response(200, metric=json_payload(metric))

    @expose("/<metric_id>/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_metric(self, metric_id: str):
        ensure_metric_tables()
        metric = metric_service().approve(metric_id_from_path(metric_id))
        db.session.commit()
        return self.response(200, metric=json_payload(metric))

    @expose("/<metric_id>/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_metric(self, metric_id: str):
        ensure_metric_tables()
        metric = metric_service().revoke(metric_id_from_path(metric_id))
        db.session.commit()
        return self.response(200, metric=json_payload(metric))

    @expose("/<metric_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_metric(self, metric_id: str):
        ensure_metric_tables()
        metric_service().delete_metric(metric_id_from_path(metric_id))
        db.session.commit()
        return self.response(200, message="Đã xóa metric.")
