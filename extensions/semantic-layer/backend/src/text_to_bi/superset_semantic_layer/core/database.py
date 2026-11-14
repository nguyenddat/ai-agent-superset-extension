import logging
from functools import wraps

from superset import db

from ..common.exceptions import SemanticLayerError

logger = logging.getLogger(__name__)


def handle_errors(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except SemanticLayerError as error:
            db.session.rollback()
            return self.response(error.status, message=str(error))
    return wrapper


def rollback_on_error(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            logger.exception("%s failed", method.__name__)
            db.session.rollback()
            return self.response_500(message="Could not save the change.")
    return wrapper
