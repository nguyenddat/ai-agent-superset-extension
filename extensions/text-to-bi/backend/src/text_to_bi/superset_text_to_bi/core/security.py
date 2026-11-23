from functools import wraps

from flask import request
from flask_wtf.csrf import validate_csrf
from wtforms import ValidationError

from .exceptions import CsrfTokenError
from .routing import error_response


def csrf_protected(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            error = CsrfTokenError()
            return error_response(error.status, error.code, str(error))
        return method(self, *args, **kwargs)
    return wrapper
