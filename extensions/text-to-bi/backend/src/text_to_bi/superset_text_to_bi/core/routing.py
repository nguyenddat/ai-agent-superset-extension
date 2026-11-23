from flask import Response, jsonify, make_response

# Every API of the extension shares one Flask-AppBuilder class permission, so a role opens all of them with
# `can_read` / `can_write`; what a caller may do inside is decided by the auth module's checks.
API_CLASS_PERMISSION = "text_to_bi_api"
OPENAPI_TAG = "Text to BI"


# Flask-AppBuilder's BaseApi.response(code, **kwargs) names the status `code`, so an error's own `code` field cannot
# pass through it.
def error_response(status: int, code: str, message: str) -> Response:
    return make_response(jsonify(code=code, message=message), status)
