import logging
from datetime import datetime, timezone
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db, security_manager
from superset.connectors.sqla.models import SqlaTable

from ....common.exceptions import SemanticLayerError
from ....common.utils.type_formatter import iso_datetime
from ....core.database import handle_errors, rollback_on_error
from ....core.exceptions import DatabaseIdRequiredError
from ....core.security import (
    can_access_dataset,
    csrf_protected,
    is_admin,
    is_superset_access_error,
    require_admin,
    require_dataset_access,
    require_semantic_layer_query,
    require_semantic_layer_view,
    second_reviewer_required,
)
from ....migrations import ensure_dictionary_tables
from ...agent_ladder.services.agent_ladder import AGENT_ORIGIN
from ...data_dictionary.dependencies import (
    column_dictionary_repository,
    dataset_dictionary_repository,
    dataset_grain_repository,
)
from ...superset.services.datasets import datasets_on_database, get_dataset, require_dataset
from ...superset.services.users import active_users, user_names
from ..dependencies import (
    metric_contract_event_repository,
    metric_contract_repository,
    metric_definition_repository,
)
from ..exceptions import (
    ApprovedContractExistsError,
    ApprovedMetricContractRequiredError,
    MetricContractNotFoundError,
    MetricContractValidationError,
    MetricExecutionDeniedError,
    MetricNotFoundError,
    MetricSelfApprovalError,
)
from ..models import MetricContract, MetricDefinition
from ..services.chart_data import latest_moment
from ..services.contracts import (
    contract_is_approved_current,
    execute_approved_chart_query,
    metric_contract_hash,
    metric_contract_ineligibility,
    metric_contract_state,
    parse_contract_metric,
)
from ..services.formula_reading import formula_row_kinds, metric_pseudo_code
from ..services.limits import (
    METRIC_DEFINITION_MAX_LENGTH,
    METRIC_UNIT_MAX_LENGTH,
    semantic_query_row_cap,
)
from ..services.metric_review import (
    metric_contract_for,
    metric_definition_for,
    metric_query_defaults_for,
    metric_query_defaults_on,
    record_metric_event,
    review_reason,
)
from ..services.query_defaults import checked_query_defaults, stored_filters

logger = logging.getLogger(__name__)


class MetricContractRoutes:
    """Routes of SemanticLayerAPI. Metric contracts: their review, business definitions, history and execution."""

    @staticmethod
    def _dataset_metric(dataset: SqlaTable, metric_id: int):
        """Resolve only a metric actually attached to this dataset."""
        return next((metric for metric in dataset.metrics if metric.id == metric_id), None)

    @staticmethod
    def _serialize_metric_contract(
        contract: MetricContract, dataset: SqlaTable, metric: Any, defaults: Any = None
    ) -> dict[str, Any]:
        """Do not expose expression/hash in execution-facing responses."""
        return {
            "id": contract.id,
            "dataset_id": contract.dataset_id,
            "metric_id": contract.metric_id,
            "metric_name": metric.metric_name,
            "status": contract.status,
            "origin": contract.origin or "manual",
            "owner_id": contract.owner_id,
            "approver_id": contract.approver_id,
            "approved_at": iso_datetime(contract.approved_at),
            "revoker_id": contract.revoker_id,
            "revoked_at": iso_datetime(contract.revoked_at),
            "current": contract_is_approved_current(contract, dataset, metric, defaults),
        }

    @staticmethod
    def _active_users() -> list[dict[str, Any]]:
        """Active Superset users an administrator can name as a metric's steward."""
        return [{"id": user.id, "name": user.get_full_name().strip() or user.username} for user in active_users()]

    @staticmethod
    def _serialize_metric_definition(definition: MetricDefinition | None, user_name: Any) -> dict[str, Any] | None:
        if definition is None:
            return None
        return {
            "business_definition": definition.business_definition,
            "unit": definition.unit,
            "steward_id": definition.steward_id,
            "steward_name": user_name(definition.steward_id),
        }

    @staticmethod
    def _query_dataset(dataset: SqlaTable) -> dict[str, Any]:
        """A dataset with the columns a metric run may group or filter by: active, physical and flagged in Superset."""
        query_columns = [
            {
                "column_name": column.column_name,
                "verbose_name": column.verbose_name,
                "type": column.type,
                "is_dttm": bool(column.is_dttm),
                "groupby": column.groupby is True,
                "filterable": column.filterable is True,
            }
            for column in dataset.columns
            if column.is_active is True
            and not column.expression
            and (column.groupby is True or column.filterable is True)
        ]
        name = f"{dataset.schema}.{dataset.table_name}" if dataset.schema else dataset.table_name
        return {"id": dataset.id, "name": name, "columns": query_columns}

    @staticmethod
    def _column_labels(datasets: list[SqlaTable]) -> dict[int, dict[str, str]]:
        """Each dataset's column labels, the data dictionary's display name over Superset's, for formula pseudo code."""
        dataset_ids = [dataset.id for dataset in datasets]
        labels: dict[int, dict[str, str]] = {
            dataset.id: {column.column_name: column.verbose_name for column in dataset.columns if column.verbose_name}
            for dataset in datasets
        }
        for column in column_dictionary_repository().list_for_datasets(dataset_ids) if dataset_ids else []:
            if column.display_name:
                labels[column.dataset_id][column.column_name] = column.display_name
        return labels

    @staticmethod
    def _metric_time_context(datasets: list[SqlaTable]) -> dict[int, dict[str, Any]]:
        """What each dataset's data dictionary says about time, for a metric's grain and time anchor: the main time
        column, the row kind column with the grain of each kind, and the date or timestamp columns a query can filter.
        """
        dataset_ids = [dataset.id for dataset in datasets]
        if not dataset_ids:
            return {}
        dictionaries = {item.id: item for item in dataset_dictionary_repository().list_by_ids(dataset_ids)}
        temporal_kinds = {
            (entry.dataset_id, entry.column_name): entry.temporal_kind
            for entry in column_dictionary_repository().list_for_datasets(dataset_ids)
        }
        row_kinds: dict[int, list[dict[str, Any]]] = {dataset_id: [] for dataset_id in dataset_ids}
        for grain in dataset_grain_repository().list_for_datasets(dataset_ids):
            row_kind = {"value": grain.row_kind_value, "label": grain.label, "grain": grain.grain}
            row_kinds[grain.dataset_id].append(row_kind)
        context = {}
        for dataset in datasets:
            dictionary = dictionaries.get(dataset.id)
            context[dataset.id] = {
                "time_column": getattr(dictionary, "time_column", None),
                "row_kind_column": getattr(dictionary, "row_kind_column", None),
                "row_kinds": row_kinds[dataset.id],
                "temporal_columns": [
                    column.column_name
                    for column in dataset.columns
                    if column.is_active is True
                    and not column.expression
                    and column.filterable is True
                    and (column.is_dttm or temporal_kinds.get((dataset.id, column.column_name)))
                ],
            }
        return context

    @expose("/metric-contracts", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_metric_contracts(self):
        """Every saved metric of one database with its contract state, parsed formula and why it is ineligible."""
        require_semantic_layer_view()
        database_id = request.args.get("database_id", type=int)
        if database_id is None:
            raise DatabaseIdRequiredError()
        ensure_dictionary_tables()
        datasets = [
            dataset
            for dataset in datasets_on_database(database_id).order_by(SqlaTable.table_name).all()
            if can_access_dataset(dataset)
        ]
        dataset_ids = [dataset.id for dataset in datasets]
        contracts = {
            (contract.dataset_id, contract.metric_id): contract
            for contract in metric_contract_repository().for_datasets(dataset_ids)
        } if dataset_ids else {}
        definitions = {
            (definition.dataset_id, definition.metric_id): definition
            for definition in metric_definition_repository().for_datasets(dataset_ids)
        } if dataset_ids else {}
        user_name = user_names()
        column_labels = self._column_labels(datasets)
        all_defaults = metric_query_defaults_on(dataset_ids)
        time_context = self._metric_time_context(datasets)
        metrics = []
        for dataset in datasets:
            for metric in dataset.metrics:
                # Every Superset dataset gets a default COUNT(*) metric; it measures no column, so it is left out.
                if metric.metric_name == "count" or str(metric.expression or "").replace(" ", "").upper() == "COUNT(*)":
                    continue
                contract = contracts.get((dataset.id, metric.id))
                defaults = all_defaults.get((dataset.id, metric.id))
                formula = parse_contract_metric(str(metric.expression or ""))
                metrics.append(
                    {
                        "dataset_id": dataset.id,
                        "metric_id": metric.id,
                        "metric_name": metric.metric_name,
                        "verbose_name": metric.verbose_name,
                        "description": metric.description,
                        "expression": metric.expression,
                        "d3format": metric.d3format,
                        "formula": formula.as_dict() if formula else None,
                        "pseudo_code": metric_pseudo_code(metric.expression, column_labels[dataset.id]),
                        "ineligibility": metric_contract_ineligibility(dataset, metric),
                        "state": metric_contract_state(contract, dataset, metric, defaults),
                        "query_defaults": defaults.as_dict() if defaults else None,
                        "contract": {
                            **self._serialize_metric_contract(contract, dataset, metric, defaults),
                            "owner_name": user_name(contract.owner_id),
                            "approver_name": user_name(contract.approver_id),
                            "revoker_name": user_name(contract.revoker_id),
                        } if contract else None,
                        "definition": self._serialize_metric_definition(
                            definitions.get((dataset.id, metric.id)), user_name
                        ),
                    }
                )
        return self.response(
            200,
            datasets=[{**self._query_dataset(dataset), **time_context[dataset.id]} for dataset in datasets],
            metrics=metrics,
            users=self._active_users(),
            current_user_id=current_user.id,
            require_second_reviewer=second_reviewer_required(),
        )

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/candidate", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_metric_contract_candidate(self, dataset_id: int, metric_id: int):
        """Snapshot a saved metric for an administrator to review."""
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id)
        if metric is None:
            raise MetricNotFoundError()
        if ineligibility := metric_contract_ineligibility(dataset, metric):
            raise MetricContractValidationError(ineligibility)
        note = review_reason(request.get_json(silent=True))
        # The AI Agent answers with this definition, so a metric must say what it means before anyone reviews it.
        if metric_definition_for(dataset_id, metric_id) is None:
            raise MetricContractValidationError("Nhập định nghĩa nghiệp vụ trước khi đề xuất metric.")
        contract = metric_contract_for(dataset_id, metric_id)
        defaults = metric_query_defaults_for(dataset_id, metric_id)
        approved = contract is not None and contract.status == "approved"
        if approved and contract_is_approved_current(contract, dataset, metric, defaults):
            raise ApprovedContractExistsError()
        # Hashing lazy-loads the dataset's database, which autoflushes the session, so it must run before a new
        # contract joins the session: a pending contract without its hash would be flushed and break NOT NULL.
        expression_hash = metric_contract_hash(dataset, metric, defaults)
        if contract is None:
            contract = MetricContract(dataset_id=dataset_id, metric_id=metric_id, owner_id=current_user.id)
        # Whoever proposes this candidate owns it, even when an earlier proposal came from someone else.
        contract.owner_id = current_user.id
        # An administrator who proposes it again takes it over, so it no longer answers as an AI Agent figure.
        contract.origin = "manual"
        contract.metric_name = metric.metric_name
        contract.expression = metric.expression
        contract.expression_hash = expression_hash
        metric_contract_repository().add(contract, flush=False)
        contract.status = "candidate"
        contract.approver_id = None
        contract.approved_at = None
        contract.revoker_id = None
        contract.revoked_at = None
        record_metric_event(dataset_id, metric_id, "candidate", note, contract)
        db.session.commit()
        return self.response(201, contract=self._serialize_metric_contract(contract, dataset, metric, defaults))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_metric_contract(self, dataset_id: int, metric_id: int):
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id)
        contract = metric_contract_for(dataset_id, metric_id) if metric else None
        if metric is None or contract is None:
            raise MetricContractNotFoundError()
        if contract.status != "candidate":
            raise MetricContractValidationError("Only a candidate metric contract can be approved.")
        proposed_by_viewer = contract.owner_id is not None and contract.owner_id == current_user.id
        if proposed_by_viewer and second_reviewer_required():
            raise MetricSelfApprovalError()
        if ineligibility := metric_contract_ineligibility(dataset, metric):
            raise MetricContractValidationError(ineligibility)
        defaults = metric_query_defaults_for(dataset_id, metric_id)
        if contract.expression_hash != metric_contract_hash(dataset, metric, defaults):
            raise MetricContractValidationError("Metric changed; create a new candidate before approval.")
        note = review_reason(request.get_json(silent=True))
        contract.status = "approved"
        contract.approver_id = current_user.id
        contract.approved_at = datetime.now(tz=timezone.utc)
        record_metric_event(dataset_id, metric_id, "approve", note, contract)
        db.session.commit()
        return self.response(200, contract=self._serialize_metric_contract(contract, dataset, metric, defaults))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_metric_contract(self, dataset_id: int, metric_id: int):
        require_admin()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id)
        contract = metric_contract_for(dataset_id, metric_id) if metric else None
        if metric is None or contract is None:
            raise MetricContractNotFoundError()
        if contract.status == "revoked":
            raise MetricContractValidationError("Metric này đã bị thu hồi.")
        reason = review_reason(request.get_json(silent=True))
        if reason is None:
            raise MetricContractValidationError("Nhập lý do thu hồi.")
        contract.status = "revoked"
        contract.revoker_id = current_user.id
        contract.revoked_at = datetime.now(tz=timezone.utc)
        record_metric_event(dataset_id, metric_id, "revoke", reason, contract)
        db.session.commit()
        defaults = metric_query_defaults_for(dataset_id, metric_id)
        return self.response(200, contract=self._serialize_metric_contract(contract, dataset, metric, defaults))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/definition", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def save_metric_definition(self, dataset_id: int, metric_id: int):
        """Save a metric's business definition, unit and steward, and log the edit in its review history."""
        require_admin()
        ensure_dictionary_tables()
        dataset = get_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id) if dataset else None
        if metric is None:
            raise MetricNotFoundError()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise MetricContractValidationError("A JSON object is required.")
        business_definition = body.get("business_definition")
        unit, steward_id = body.get("unit"), body.get("steward_id")
        if not isinstance(business_definition, str) or not business_definition.strip():
            raise MetricContractValidationError("Định nghĩa nghiệp vụ không được để trống.")
        if len(business_definition) > METRIC_DEFINITION_MAX_LENGTH:
            raise MetricContractValidationError(f"Định nghĩa nghiệp vụ tối đa {METRIC_DEFINITION_MAX_LENGTH} ký tự.")
        if unit is not None and (not isinstance(unit, str) or len(unit) > METRIC_UNIT_MAX_LENGTH):
            raise MetricContractValidationError(f"Đơn vị phải là văn bản tối đa {METRIC_UNIT_MAX_LENGTH} ký tự.")
        valid_steward_id = isinstance(steward_id, int) and not isinstance(steward_id, bool)
        if steward_id is not None and (not valid_steward_id or security_manager.get_user_by_id(steward_id) is None):
            raise MetricContractValidationError("Người phụ trách không tồn tại.")
        definition = metric_definition_for(dataset_id, metric_id)
        if definition is None:
            definition = MetricDefinition(dataset_id=dataset_id, metric_id=metric_id)
        definition.business_definition = business_definition.strip()
        definition.unit = (unit or "").strip() or None
        definition.steward_id = steward_id
        metric_definition_repository().add(definition, flush=False)
        record_metric_event(dataset_id, metric_id, "definition")
        db.session.commit()
        return self.response(200, definition=self._serialize_metric_definition(definition, user_names()))

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/query-defaults", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def save_metric_query_defaults(self, dataset_id: int, metric_id: int):
        """Save a metric's grain, time anchor and default filters, checked against its dataset and formula.

        They are part of what the metric means, so a change makes an approved or proposed contract outdated until it is
        proposed and approved again, as a formula edit does.
        """
        require_admin()
        ensure_dictionary_tables()
        dataset = get_dataset(dataset_id)
        metric = self._dataset_metric(dataset, metric_id) if dataset else None
        if metric is None:
            raise MetricNotFoundError()
        definition = metric_definition_for(dataset_id, metric_id)
        if definition is None:
            raise MetricContractValidationError(
                "Nhập định nghĩa nghiệp vụ trước khi đặt grain, mốc thời gian và bộ lọc mặc định."
            )
        context = self._metric_time_context([dataset])[dataset.id]
        formula = parse_contract_metric(str(metric.expression or ""))
        defaults = checked_query_defaults(
            request.get_json(silent=True),
            {column.column_name: column for column in dataset.columns},
            temporal_columns=set(context["temporal_columns"]),
            dataset_time_column=context["time_column"],
            row_kind_column=context["row_kind_column"],
            grains={item["value"]: item["grain"] for item in context["row_kinds"]},
            formula_row_kinds=formula_row_kinds(formula, context["row_kind_column"]) if formula else set(),
        )
        definition.grain = defaults.grain
        definition.row_kind_value = defaults.row_kind_value
        definition.time_column = defaults.time_column
        definition.time_window = defaults.time_window
        definition.time_anchor = defaults.time_anchor
        definition.default_filters = stored_filters(defaults)
        metric_definition_repository().add(definition, flush=False)
        record_metric_event(dataset_id, metric_id, "definition", "Đổi grain, mốc thời gian hoặc bộ lọc mặc định.")
        db.session.commit()
        saved = None if defaults.is_empty() else defaults
        return self.response(
            200,
            query_defaults=saved.as_dict() if saved else None,
            state=metric_contract_state(metric_contract_for(dataset_id, metric_id), dataset, metric, saved),
        )

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/contract/events", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_metric_contract_events(self, dataset_id: int, metric_id: int):
        """A metric's review history, newest first."""
        require_semantic_layer_view()
        ensure_dictionary_tables()
        require_dataset_access(require_dataset(dataset_id))
        events = metric_contract_event_repository().history(dataset_id, metric_id)
        user_name = user_names()
        return self.response(
            200,
            events=[
                {
                    "id": event.id,
                    "action": event.action,
                    "actor_id": event.actor_id,
                    "actor_name": user_name(event.actor_id),
                    "reason": event.reason,
                    "expression": event.expression,
                    "created_at": iso_datetime(event.created_at),
                }
                for event in events
            ],
        )

    @expose("/dataset/<int:dataset_id>/metrics/<int:metric_id>/semantic-query/execute", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def execute_metric_contract(self, dataset_id: int, metric_id: int):
        """Run a current approved metric, or let an administrator preview a candidate, through Superset ChartData."""
        require_semantic_layer_query()
        ensure_dictionary_tables()
        dataset = require_dataset(dataset_id)
        require_dataset_access(dataset)
        metric = self._dataset_metric(dataset, metric_id)
        contract = metric_contract_for(dataset_id, metric_id) if metric else None
        if metric is None:
            raise ApprovedMetricContractRequiredError()
        body = request.get_json(silent=True)
        try:
            # validate() is Superset's datasource/RLS permission gate and runs as
            # the request's current_user; this route never compiles or runs SQL.
            from superset.charts.schemas import ChartDataQueryContextSchema
            from superset.commands.chart.data.get_data_command import ChartDataCommand

            def run_chart(payload):
                command = ChartDataCommand(ChartDataQueryContextSchema().load(payload))
                command.validate()
                return command.run()["queries"][0]

            # Administrators may preview a candidate so a reviewer sees real numbers before approving it; a candidate
            # the AI Agent built answers anyone as a provisional figure until it is approved or revoked.
            provisional = getattr(contract, "origin", None) == AGENT_ORIGIN
            defaults = metric_query_defaults_for(dataset_id, metric_id)
            result = execute_approved_chart_query(
                contract,
                dataset,
                metric,
                body,
                semantic_query_row_cap(),
                run_chart,
                allow_candidate=is_admin() or provisional,
                defaults=defaults,
                latest_time=lambda filters: latest_moment(dataset, defaults.time_column, filters),
            )
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
            return self.response_500(message="Metric execution was rejected by Superset.")
        if result.get("error"):
            return self.response_500(message="Metric execution failed.")
        rows = result.get("data", [])
        return self.response(
            200,
            columns=result.get("colnames", []),
            rows=rows[: semantic_query_row_cap()],
            row_count=min(len(rows), semantic_query_row_cap()),
            truncated=len(rows) > semantic_query_row_cap(),
            # The SQL Superset ran, RLS predicates included, so only administrators see it.
            sql=result.get("query") if is_admin() else None,
            preview=contract is not None and contract.status == "candidate",
            # The metric's row kind, default filters, time window and grain this run used, so the caller can say so.
            applied_defaults=result.get("applied_defaults"),
        )
