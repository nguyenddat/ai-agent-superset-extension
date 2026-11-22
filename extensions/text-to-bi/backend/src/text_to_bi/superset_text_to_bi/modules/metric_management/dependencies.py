from superset.extensions import db

from .services import MetricService


def metric_service() -> MetricService:
    return MetricService(db.session)
