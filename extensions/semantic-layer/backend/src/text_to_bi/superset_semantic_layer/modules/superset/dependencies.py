from functools import wraps

from flask import request

from text_to_bi.superset_semantic_layer.core.exceptions import DatabaseIdRequiredError

from .exceptions import DatasetMetricNotFoundError
from .services.srv_dataset import require_database, require_dataset
from .services.srv_user import require_user

# Each decorator takes the ID it reads out of the URL arguments and hands the route the object instead, so a route
# receives `dataset`, `metric`, `database` or `user` and never the raw ID.


def requires_dataset(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        dataset = require_dataset(kwargs.pop("dataset_id"))
        return method(self, *args, dataset=dataset, **kwargs)
    return wrapper


def requires_metric(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        dataset = require_dataset(kwargs.pop("dataset_id"))
        metric_id = kwargs.pop("metric_id")
        metric = next((item for item in dataset.metrics if item.id == metric_id), None)
        if metric is None:
            raise DatasetMetricNotFoundError()
        return method(self, *args, dataset=dataset, metric=metric, **kwargs)
    return wrapper


def requires_database(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        database_id = kwargs.pop("database_id", None) or request.args.get("database_id", type=int)
        if database_id is None:
            raise DatabaseIdRequiredError()
        return method(self, *args, database=require_database(database_id), **kwargs)
    return wrapper


def requires_user(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        return method(self, *args, user=require_user(kwargs.pop("user_id")), **kwargs)
    return wrapper
