# Every API of the extension shares one Flask-AppBuilder class permission, so a role opens all of them with
# `can_read` / `can_write`; what a caller may do inside is decided by the auth module's checks.
API_CLASS_PERMISSION = "text_to_bi_api"
OPENAPI_TAG = "Text to BI"
