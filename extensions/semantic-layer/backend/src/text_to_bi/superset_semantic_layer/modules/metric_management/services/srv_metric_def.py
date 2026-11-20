from typing import Any

from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.core.config import settings
from text_to_bi.superset_semantic_layer.modules.superset import SupersetUserNotFoundError, require_user

from ..dependencies import metric_contract_repository, metric_definition_repository
from ..exceptions import MetricContractValidationError, MetricDefinitionNotFoundError
from ..models import MetricDefinition
from .srv_metric_event import MetricEventService
from .srv_metric_formula import formula_row_kinds, parse_contract_metric
from .srv_metric_query_defaults import MetricQueryDefaults, checked_query_defaults, dataset_time_context


class MetricDefService:
    def __init__(self) -> None:
        self.definitions = metric_definition_repository()
        self.contracts = metric_contract_repository()
        self.events = MetricEventService()

    # -------------------------READ---------------------------
    def read(self, dataset: Any, metric: Any) -> MetricDefinition | None:
        definition = self.definitions.read_by_metric(metric.id)
        return definition if definition is not None and definition.dataset_id == dataset.id else None

    def require(self, dataset: Any, metric: Any) -> MetricDefinition:
        definition = self.read(dataset, metric)
        if definition is None:
            raise MetricDefinitionNotFoundError()
        return definition

    # -------------------------UPDATE-------------------------
    def update(self, dataset: Any, metric: Any, body: Any) -> MetricDefinition:
        values = self._checked_definition(body)
        definition = self.read(dataset, metric)
        if definition is None:
            definition = self.definitions.create({**values, "dataset_id": dataset.id, "metric_id": metric.id})
        else:
            self.definitions.update(definition, values)

        self.events.create(definition, metric, "definition")
        return definition

    def update_query_defaults(self, dataset: Any, metric: Any, body: Any) -> MetricQueryDefaults:
        definition = self.read(dataset, metric)
        if definition is None:
            raise MetricContractValidationError(
                "Nhập định nghĩa nghiệp vụ trước khi đặt grain, mốc thời gian và bộ lọc mặc định."
            )

        formula = parse_contract_metric(str(metric.expression or ""))
        context = dataset_time_context(dataset)
        defaults = checked_query_defaults(
            body,
            {column.column_name: column for column in dataset.columns},
            context,
            formula_row_kinds(formula, context.row_kind_column) if formula else set(),
        )
        self.definitions.update(definition, defaults.stored_values())
        self.events.create(definition, metric, "definition", "Đổi grain, mốc thời gian hoặc bộ lọc mặc định.")
        return defaults

    # -------------------------DELETE-------------------------
    def delete(self, dataset: Any, metric: Any) -> None:
        definition = self.require(dataset, metric)
        contract = self.contracts.read_by_definition(definition.id)
        if contract is not None and contract.status == ReviewStatus.APPROVED:
            raise MetricContractValidationError("Thu hồi metric trước khi xóa định nghĩa nghiệp vụ.")

        self.events.create(definition, metric, "definition", "Xóa định nghĩa nghiệp vụ.")
        if contract is not None:
            self.contracts.delete(contract)

        self.definitions.delete(definition)

    @staticmethod
    def _checked_definition(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise MetricContractValidationError("Nội dung gửi lên phải là một đối tượng JSON.")

        business_definition = body.get("business_definition")
        unit, steward_id = body.get("unit"), body.get("steward_id")
        if not isinstance(business_definition, str) or not business_definition.strip():
            raise MetricContractValidationError("Định nghĩa nghiệp vụ không được để trống.")
        definition_limit, unit_limit = settings.METRIC_DEFINITION_MAX_LENGTH, settings.METRIC_UNIT_MAX_LENGTH
        if len(business_definition) > definition_limit:
            raise MetricContractValidationError(f"Định nghĩa nghiệp vụ tối đa {definition_limit} ký tự.")
        if unit is not None and (not isinstance(unit, str) or len(unit) > unit_limit):
            raise MetricContractValidationError(f"Đơn vị phải là văn bản tối đa {unit_limit} ký tự.")

        if steward_id is not None:
            if not isinstance(steward_id, int) or isinstance(steward_id, bool):
                raise MetricContractValidationError("Người phụ trách không tồn tại.")
            try:
                require_user(steward_id)
            except SupersetUserNotFoundError as error:
                raise MetricContractValidationError("Người phụ trách không tồn tại.") from error

        return {
            "business_definition": business_definition.strip(),
            "unit": (unit or "").strip() or None,
            "steward_id": steward_id,
        }
