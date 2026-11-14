import logging
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db

from text_to_bi.superset_semantic_layer.common.exceptions import SemanticLayerError
from text_to_bi.superset_semantic_layer.common.public import public_payload
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import (
    can_access_dataset,
    csrf_protected,
    is_superset_access_error,
    require_admin,
    require_dataset_access,
    require_semantic_layer_query,
    require_semantic_layer_view,
    second_reviewer_required,
)
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.superset import requires_database, requires_metric
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import datasets_on_database
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import active_users

from ..exceptions import MetricContractValidationError, MetricExecutionDeniedError
from ..models import MetricContract
from ..services.srv_metric_contract import MetricContractService, metric_contract_state
from ..services.srv_metric_event import MetricEventService
from ..services.srv_metric_execute import MetricExecuteService, run_chart_query
from ..services.srv_metric_query_defaults import dataset_column_labels, dataset_time_contexts
from ..utils.util_serializer import (
    serialize_metric_contract,
    serialize_metric_entry,
    serialize_metric_events,
    serialize_query_dataset,
    serialize_users,
)

logger = logging.getLogger(__name__)

prefix = "/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract"


class MetricContractRoutes(RouteMixin):
    # -------------------------READ---------------------------
    @expose("/metric-contracts", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    @requires_database
    def read_metric_contracts(self, database: Any):
        """Mọi metric của một database kèm trạng thái duyệt, định nghĩa và giá trị mặc định (`?database_id=`)."""
        require_semantic_layer_view()
        ensure_dictionary_tables()
        datasets = [dataset for dataset in datasets_on_database(database.id) if can_access_dataset(dataset)]
        entries = MetricContractService().read_entries(datasets)
        column_labels = dataset_column_labels(datasets)
        time_contexts = dataset_time_contexts(datasets)
        return self.response(
            200,
            datasets=[
                serialize_query_dataset(dataset, column_labels[dataset.id], time_contexts[dataset.id])
                for dataset in datasets
            ],
            metrics=[serialize_metric_entry(entry) for entry in entries],
            users=serialize_users(active_users()),
            current_user_id=current_user.id,
            require_second_reviewer=second_reviewer_required(),
        )

    @expose(prefix, methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    @requires_metric
    def read_metric_contract(self, dataset: Any, metric: Any):
        """Bản duyệt và trạng thái duyệt của metric."""
        require_semantic_layer_view()
        require_dataset_access(dataset)
        ensure_dictionary_tables()
        service = MetricContractService()
        return self.response(200, contract=self._serialized(service, service.read(dataset, metric), dataset, metric))

    @expose(f"{prefix}/events", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    @requires_metric
    def read_metric_contract_events(self, dataset: Any, metric: Any):
        """Lịch sử duyệt của metric, mới nhất trước."""
        require_semantic_layer_view()
        ensure_dictionary_tables()
        require_dataset_access(dataset)
        return self.response(200, events=serialize_metric_events(MetricEventService().read_history(metric)))

    # -------------------------CREATE-------------------------
    @expose(f"{prefix}/candidate", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_metric
    def create_metric_contract(self, dataset: Any, metric: Any):
        """Đề xuất metric: tạo bản nháp chờ duyệt từ công thức hiện tại."""
        require_admin()
        ensure_dictionary_tables()
        service = MetricContractService()
        contract = service.propose(dataset, metric, request.get_json(silent=True))
        db.session.commit()
        return self.response(201, contract=self._serialized(service, contract, dataset, metric))

    # -------------------------UPDATE-------------------------
    @expose(f"{prefix}/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_metric
    def approve_metric_contract(self, dataset: Any, metric: Any):
        """Duyệt bản nháp của metric."""
        require_admin()
        ensure_dictionary_tables()
        service = MetricContractService()
        contract = service.approve(dataset, metric, request.get_json(silent=True))
        db.session.commit()
        return self.response(200, contract=self._serialized(service, contract, dataset, metric))

    @expose(f"{prefix}/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_metric
    def revoke_metric_contract(self, dataset: Any, metric: Any):
        """Thu hồi metric, kèm lý do."""
        require_admin()
        ensure_dictionary_tables()
        service = MetricContractService()
        contract = service.revoke(dataset, metric, request.get_json(silent=True))
        db.session.commit()
        return self.response(200, contract=self._serialized(service, contract, dataset, metric))

    # -------------------------EXECUTE------------------------
    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/semantic-query/execute", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_metric
    def execute_metric_contract(self, dataset: Any, metric: Any):
        """Chạy metric đã duyệt qua ChartData của Superset; admin chạy thử được bản nháp."""
        require_semantic_layer_query()
        ensure_dictionary_tables()
        require_dataset_access(dataset)
        try:
            result = MetricExecuteService().execute(dataset, metric, request.get_json(silent=True), run_chart_query)
        except SemanticLayerError:
            raise
        except ValueError as error:
            # Superset's own message may name internals, so the client gets a fixed one.
            logger.warning("Superset ChartData refused the metric query: %s", error)
            raise MetricContractValidationError("Superset không nhận truy vấn metric này.") from error
        except Exception as error:
            db.session.rollback()
            if is_superset_access_error(error):
                raise MetricExecutionDeniedError() from error
            logger.exception("Superset ChartData metric execution failed")
            return self.response_500(message="Superset không chạy được truy vấn metric này.")
        if result.pop("error"):
            return self.response_500(message="Truy vấn metric chạy không thành công.")
        return self.response(200, **public_payload(result))

    # -------------------------HELPERS------------------------
    @staticmethod
    def _serialized(
        service: MetricContractService, contract: MetricContract | None, dataset: Any, metric: Any
    ) -> dict[str, Any]:
        state = metric_contract_state(contract, dataset, metric, service.query_defaults(dataset, metric))
        return serialize_metric_contract(contract, metric, state)
