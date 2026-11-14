from superset import db

from .repositories.repo_metric_contract import MetricContractRepository
from .repositories.repo_metric_contract_event import MetricContractEventRepository
from .repositories.repo_metric_definition import MetricDefinitionRepository


def metric_definition_repository() -> MetricDefinitionRepository:
    return MetricDefinitionRepository(db.session)


def metric_contract_repository() -> MetricContractRepository:
    return MetricContractRepository(db.session)


def metric_contract_event_repository() -> MetricContractEventRepository:
    return MetricContractEventRepository(db.session)
