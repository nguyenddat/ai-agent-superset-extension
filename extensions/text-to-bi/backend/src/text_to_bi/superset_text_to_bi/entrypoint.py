"""Register the Text to BI backend APIs with Superset."""

from .modules.auth.routes.route_auth import AuthAPI  # noqa: F401
from .modules.auth.services.srv_roles import declare_text_to_bi_admin_only
from .modules.data_dictionary.routes.route_data_dictionary import DataDictionaryAPI  # noqa: F401

# Superset's role synchronization must not grant these extension permissions to default roles.
declare_text_to_bi_admin_only()
