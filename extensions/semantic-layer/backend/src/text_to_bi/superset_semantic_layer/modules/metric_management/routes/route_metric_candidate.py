import logging
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset.connectors.sqla.models import SqlaTable, SqlMetric

from text_to_bi.superset_semantic_layer.common.public import public_payload
from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.exceptions import DatasetIdRequiredError
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import (
    csrf_protected,
    require_dataset_access,
    require_semantic_layer_query,
)
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.data_dictionary.dependencies import dataset_dictionary_repository
from text_to_bi.superset_semantic_layer.modules.data_dictionary.exceptions import DatasetDraftValidationError
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_dataset_draft import (
    AGENT_ORIGIN,
    AGGREGATE_DATASET,
    MAX_PENDING_AGENT_METRICS,
    asked_question,
    checked_metric_draft,
    matching_metric,
    unique_metric_name,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import (
    is_internal_dataset,
    require_dataset,
)

from ..dependencies import (
    metric_definition_repository,
)
from ..exceptions import (
    AgentMetricPendingError,
    AgentMetricRevokedError,
    AggregateDatasetRequiredError,
    TooManyPendingAgentMetricsError,
)
from ..services.srv_metric_contract import (
    MetricContractService,
    metric_contract_state,
)

logger = logging.getLogger(__name__)



class MetricCandidateRoutes(RouteMixin):
    @expose("/metric-candidates", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_agent_metric(self):
        """Save the metric the AI Agent built on an aggregate dataset as a candidate for review, or reuse one.

        A metric with the same formula already on the dataset is reused: an approved one answers as it is, one the agent
        proposed earlier answers as provisional again. A new metric gets its business definition and an AI Agent
        candidate contract, so it answers the asker at once as a provisional figure and waits for an administrator.
        """
        require_semantic_layer_query()
        ensure_dictionary_tables()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise DatasetDraftValidationError("A JSON object is required.")
        dataset_id = body.get("dataset_id")
        if not isinstance(dataset_id, int) or isinstance(dataset_id, bool):
            raise DatasetIdRequiredError()
        dataset = require_dataset(dataset_id)
        dictionary = dataset_dictionary_repository().read(dataset_id)
        if getattr(dictionary, "dataset_type", None) != AGGREGATE_DATASET or is_internal_dataset(dataset):
            raise AggregateDatasetRequiredError()
        require_dataset_access(dataset)
        draft = checked_metric_draft(body, dataset)
        question = asked_question(body)

        contracts = MetricContractService()
        metric = matching_metric(dataset, draft.expression)
        contract = contracts.read(dataset, metric) if metric is not None else None
        if contract is not None:
            state = metric_contract_state(contract, dataset, metric, contracts.query_defaults(dataset, metric))
            if state == ReviewStatus.APPROVED.value:
                return self.response(200, **public_payload({'metric': self._agent_metric(dataset, metric), 'provisional': False}))
            if state == ReviewStatus.DRAFT.value and contract.origin == AGENT_ORIGIN:
                return self.response(200, **public_payload({'metric': self._agent_metric(dataset, metric), 'provisional': True}))
            if state == ReviewStatus.REVOKED.value:
                raise AgentMetricRevokedError()
            raise AgentMetricPendingError()
        if metric is None:
            if contracts.count_agent_drafts(dataset) >= MAX_PENDING_AGENT_METRICS:
                raise TooManyPendingAgentMetricsError()
            metric = SqlMetric(
                metric_name=unique_metric_name(dataset, draft.metric_name),
                verbose_name=draft.label,
                expression=draft.expression,
                description=draft.definition,
            )
            dataset.metrics.append(metric)
            db.session.flush()
        note = f"AI Agent đề xuất khi trả lời: {question}" if question else "AI Agent đề xuất."
        contracts.propose_for_agent(dataset, metric, draft.definition, draft.unit, note, current_user.id)
        db.session.commit()
        return self.response(201, **public_payload({'metric': self._agent_metric(dataset, metric), 'provisional': True}))

    def _agent_metric(self, dataset: SqlaTable, metric: Any) -> dict[str, Any]:
        """The metric in the shape of a semantic catalog metric, which the agent queries like an approved one."""
        definition = metric_definition_repository().read_by_metric(metric.id)
        return {
            "dataset_id": dataset.id,
            "metric_id": metric.id,
            "metric_name": metric.metric_name,
            "verbose_name": metric.verbose_name,
            "expression": metric.expression,
            "business_definition": getattr(definition, "business_definition", None) or metric.description,
            "unit": getattr(definition, "unit", None),
            "d3format": metric.d3format,
        }
