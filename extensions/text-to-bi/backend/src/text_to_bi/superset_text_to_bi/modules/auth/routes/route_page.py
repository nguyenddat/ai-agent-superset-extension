from flask import abort, redirect
from flask_appbuilder import expose
from superset import appbuilder
from superset.views.base import BaseSupersetView

from text_to_bi.superset_text_to_bi.common.utils.request_user import request_user

from ..services.srv_access import can_query_datasets, can_view


# Superset serves its own app shell at /text-to-bi/; the extension's frontend mounts its page into it.
class TextToBIView(BaseSupersetView):
    route_base = "/text-to-bi"

    @expose("/")
    def page(self):
        if request_user() is None:
            return redirect(appbuilder.get_url_for_login)
        if not (can_view() or can_query_datasets()):
            abort(403)
        return self.render_app_template()


appbuilder.add_view_no_menu(TextToBIView)
