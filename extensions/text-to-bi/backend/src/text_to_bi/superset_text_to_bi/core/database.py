import logging
from functools import wraps

from superset.extensions import db

from text_to_bi.superset_text_to_bi.common.base_exceptions import AppError

logger = logging.getLogger(__name__)

INTERNAL_ERROR_CODE = "internal_error"
INTERNAL_ERROR_MESSAGE = "Đã xảy ra lỗi hệ thống."


# Sits under @safe and @rollback_on_error, which would turn every exception into a 500: an AppError becomes its own
# status with {"code", "message"}, and the session is rolled back so nothing half-done is kept.
def handle_errors(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except AppError as error:
            db.session.rollback()
            return self.response(error.status, code=error.code, message=str(error))
    return wrapper


def rollback_on_error(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            logger.exception("%s failed", method.__name__)
            db.session.rollback()
            return self.response(500, code=INTERNAL_ERROR_CODE, message=INTERNAL_ERROR_MESSAGE)
    return wrapper
