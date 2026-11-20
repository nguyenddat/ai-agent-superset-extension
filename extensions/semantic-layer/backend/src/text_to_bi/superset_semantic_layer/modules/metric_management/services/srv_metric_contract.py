import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from flask_login import current_user

from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.common.utils.type_formatter import canonical_json
from text_to_bi.superset_semantic_layer.core.config import settings
from text_to_bi.superset_semantic_layer.core.security import second_reviewer_required
from text_to_bi.superset_semantic_layer.modules.data_dictionary.dependencies import (
    column_dictionary_repository,
    dataset_dictionary_repository,
    dataset_grain_repository,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import connection_identity

from ..dependencies import metric_contract_repository, metric_definition_repository
from ..exceptions import (
    ApprovedMetricContractExistsError,
    MetricContractNotFoundError,
    MetricContractValidationError,
    MetricSelfApprovalError,
)
from ..models import MetricContract, MetricDefinition
from ..schemas.status_enum import ContractOrigin
from .srv_metric_event import MetricEventService
from .srv_metric_formula import parse_contract_metric
from .srv_metric_query_defaults import MetricQueryDefaults, query_defaults_for, query_defaults_on
from .srv_metric_validation import metric_contract_ineligibility, metric_semantic_ineligibility

# States shown to an administrator besides the stored statuses; `outdated` is a draft or approval whose metric
# changed after it was recorded.
NOT_STARTED, INELIGIBLE, OUTDATED = "not_started", "ineligible", "outdated"


@dataclass(frozen=True)
class MetricEntry:
    dataset: Any
    metric: Any
    contract: MetricContract | None
    definition: MetricDefinition | None
    defaults: MetricQueryDefaults | None
    state: str
    ineligibility: str | None


class MetricContractService:
    def __init__(self) -> None:
        self.contracts = metric_contract_repository()
        self.definitions = metric_definition_repository()
        self.events = MetricEventService()

    # -------------------------READ---------------------------
    def read(self, dataset: Any, metric: Any) -> MetricContract | None:
        contract = self.contracts.read_by_metric(metric.id)
        return contract if contract is not None and contract.dataset_id == dataset.id else None

    def require(self, dataset: Any, metric: Any) -> MetricContract:
        contract = self.read(dataset, metric)
        if contract is None:
            raise MetricContractNotFoundError()
        return contract

    def _definition(self, dataset: Any, metric: Any) -> MetricDefinition | None:
        definition = self.definitions.read_by_metric(metric.id)
        return definition if definition is not None and definition.dataset_id == dataset.id else None

    def query_defaults(self, dataset: Any, metric: Any) -> MetricQueryDefaults | None:
        return query_defaults_for(dataset.id, metric.id)

    def read_entries(self, datasets: list[Any]) -> list[MetricEntry]:
        dataset_ids = [dataset.id for dataset in datasets]
        contracts = {item.metric_id: item for item in self.contracts.read_on_datasets(dataset_ids)}
        definitions = {item.metric_id: item for item in self.definitions.read_on_datasets(dataset_ids)}
        all_defaults = query_defaults_on(dataset_ids)
        entries = []
        for dataset in datasets:
            for metric in dataset.metrics:
                # Every Superset dataset gets a default COUNT(*) metric; it measures no column, so it is left out.
                if metric.metric_name == "count" or str(metric.expression or "").replace(" ", "").upper() == "COUNT(*)":
                    continue
                contract = contracts.get(metric.id)
                defaults = all_defaults.get((dataset.id, metric.id))
                entries.append(
                    MetricEntry(
                        dataset=dataset,
                        metric=metric,
                        contract=contract,
                        definition=definitions.get(metric.id),
                        defaults=defaults,
                        state=metric_contract_state(contract, dataset, metric, defaults),
                        ineligibility=self._ineligibility(
                            dataset, metric, getattr(definitions.get(metric.id), "unit", None)
                        ),
                    )
                )
        return entries

    # -------------------------CREATE-------------------------
    def propose(self, dataset: Any, metric: Any, body: Any) -> MetricContract:
        note = review_reason(body)
        # The AI Agent answers with this definition, so a metric must say what it means before anyone reviews it.
        definition = self._definition(dataset, metric)
        if definition is None:
            raise MetricContractValidationError("Nhập định nghĩa nghiệp vụ trước khi đề xuất metric.")
        if ineligibility := self._ineligibility(dataset, metric, definition.unit):
            raise MetricContractValidationError(ineligibility)
        defaults = self.query_defaults(dataset, metric)
        contract = self.read(dataset, metric)
        if contract is not None and contract_is_approved_current(contract, dataset, metric, defaults):
            raise ApprovedMetricContractExistsError()

        # Hashing lazy-loads the dataset's database, which autoflushes the session, so it runs before a new
        # contract joins the session: a pending contract without its hash would break NOT NULL.
        values = {
            "metric_name": metric.metric_name,
            "expression": metric.expression,
            "expression_hash": metric_contract_hash(dataset, metric, defaults),
            "status": ReviewStatus.DRAFT.value,
            # Whoever proposes owns it; an administrator taking over an AI Agent draft makes it manual.
            "owner_id": current_user.id,
            "origin": ContractOrigin.MANUAL.value,
            "approver_id": None,
            "approved_at": None,
            "revoker_id": None,
            "revoked_at": None,
        }
        if contract is None:
            contract = self.contracts.create({**values, "definition_id": definition.id})
        else:
            self.contracts.update(contract, values)

        self.events.create(definition, metric, "candidate", note, contract)
        return contract

    def propose_for_agent(
        self, dataset: Any, metric: Any, business_definition: str, unit: str | None, note: str, owner_id: int | None
    ) -> MetricContract:
        definition = self._definition(dataset, metric)
        if ineligibility := self._ineligibility(dataset, metric, unit if definition is None else definition.unit):
            raise MetricContractValidationError(ineligibility)
        if definition is None:
            definition = self.definitions.create(
                {
                    "dataset_id": dataset.id,
                    "metric_id": metric.id,
                    "business_definition": business_definition,
                    "unit": unit,
                }
            )
        # Hashing lazy-loads the dataset's database, which autoflushes, so it runs before the contract is added.
        expression_hash = metric_contract_hash(dataset, metric, self.query_defaults(dataset, metric))
        contract = self.contracts.create(
            {
                "definition_id": definition.id,
                "metric_name": metric.metric_name,
                "expression": metric.expression,
                "expression_hash": expression_hash,
                "status": ReviewStatus.DRAFT.value,
                "origin": ContractOrigin.AI_AGENT.value,
                "owner_id": owner_id,
            }
        )
        self.events.create(definition, metric, "candidate", note, contract)
        return contract

    def count_agent_drafts(self, dataset: Any) -> int:
        return self.contracts.count_on(dataset.id, origin=ContractOrigin.AI_AGENT.value, status=ReviewStatus.DRAFT)

    # -------------------------UPDATE-------------------------
    def approve(self, dataset: Any, metric: Any, body: Any) -> MetricContract:
        contract = self.require(dataset, metric)
        if contract.status != ReviewStatus.DRAFT:
            raise MetricContractValidationError("Chỉ duyệt được metric đang chờ duyệt.")
        if contract.owner_id is not None and contract.owner_id == current_user.id and second_reviewer_required():
            raise MetricSelfApprovalError()
        if ineligibility := self._ineligibility(dataset, metric, contract.definition.unit):
            raise MetricContractValidationError(ineligibility)
        if contract.expression_hash != metric_contract_hash(dataset, metric, self.query_defaults(dataset, metric)):
            raise MetricContractValidationError("Metric đã đổi sau lần đề xuất; tạo bản đề xuất mới trước khi duyệt.")

        note = review_reason(body)
        self.contracts.update(
            contract,
            {
                "status": ReviewStatus.APPROVED.value,
                "approver_id": current_user.id,
                "approved_at": datetime.now(tz=timezone.utc),
            },
        )
        self.events.create(contract.definition, metric, "approve", note, contract)
        return contract

    @staticmethod
    def _ineligibility(dataset: Any, metric: Any, metric_unit: str | None = None) -> str | None:
        if ineligibility := metric_contract_ineligibility(dataset, metric):
            return ineligibility
        definition = dataset_dictionary_repository().read(dataset.id)
        if definition is None:
            return "Khai báo Từ điển dữ liệu của dataset trước khi duyệt metric."
        columns = {entry.column_name: entry for entry in column_dictionary_repository().read_by_dataset(dataset.id)}
        grains = {grain.row_kind_value: grain.grain for grain in dataset_grain_repository().read_by_dataset(dataset.id)}
        return metric_semantic_ineligibility(
            dataset, metric, columns, metric_unit, grains, getattr(definition, "row_kind_column", None)
        )

    def revoke(self, dataset: Any, metric: Any, body: Any) -> MetricContract:
        contract = self.require(dataset, metric)
        if contract.status == ReviewStatus.REVOKED:
            raise MetricContractValidationError("Metric này đã bị thu hồi.")
        reason = review_reason(body)
        if reason is None:
            raise MetricContractValidationError("Nhập lý do thu hồi.")

        self.contracts.update(
            contract,
            {
                "status": ReviewStatus.REVOKED.value,
                "revoker_id": current_user.id,
                "revoked_at": datetime.now(tz=timezone.utc),
            },
        )
        self.events.create(contract.definition, metric, "revoke", reason, contract)
        return contract


# -------------------------CHECK--------------------------


def metric_contract_hash(dataset: Any, metric: Any, defaults: MetricQueryDefaults | None = None) -> str:
    formula = parse_contract_metric(str(metric.expression or ""))
    live_columns = {column.column_name: column for column in dataset.columns}
    metric_column = live_columns.get(formula.measure_column) if formula and formula.measure_column else None
    payload = {
        "dataset_id": dataset.id,
        "metric_id": metric.id,
        "metric_name": str(metric.metric_name or ""),
        "expression": str(metric.expression or ""),
        "catalog": getattr(dataset, "catalog", None),
        "schema": dataset.schema,
        "table": dataset.table_name,
        "sql": dataset.sql,
        "datasource_type": "virtual" if dataset.sql else "physical",
        "database": connection_identity(dataset.database),
        "metric_column_expression": getattr(metric_column, "expression", None),
    }
    # A metric without defaults keeps the hash it had before defaults existed.
    if defaults is not None and not defaults.is_empty():
        payload["query_defaults"] = defaults.as_dict()
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def contract_is_approved_current(
    contract: MetricContract, dataset: Any, metric: Any, defaults: MetricQueryDefaults | None = None
) -> bool:
    return (
        contract.status == ReviewStatus.APPROVED
        and contract.dataset_id == dataset.id
        and contract.metric_id == metric.id
        and metric_contract_ineligibility(dataset, metric) is None
        and contract.expression_hash == metric_contract_hash(dataset, metric, defaults)
    )


def metric_contract_state(
    contract: MetricContract | None, dataset: Any, metric: Any, defaults: MetricQueryDefaults | None = None
) -> str:
    eligible = metric_contract_ineligibility(dataset, metric) is None
    if contract is None:
        return NOT_STARTED if eligible else INELIGIBLE
    if contract.status == ReviewStatus.REVOKED:
        return ReviewStatus.REVOKED.value
    if contract.status == ReviewStatus.APPROVED:
        current = contract_is_approved_current(contract, dataset, metric, defaults)
        return ReviewStatus.APPROVED.value if current else OUTDATED
    unchanged = eligible and contract.expression_hash == metric_contract_hash(dataset, metric, defaults)
    return ReviewStatus.DRAFT.value if unchanged else OUTDATED


def review_reason(body: Any) -> str | None:
    reason = body.get("reason") if isinstance(body, dict) else None
    if reason is None:
        return None
    limit = settings.METRIC_REVIEW_REASON_MAX_LENGTH
    if not isinstance(reason, str) or len(reason) > limit:
        raise MetricContractValidationError(f"Lý do phải là văn bản tối đa {limit} ký tự.")
    return reason.strip() or None
