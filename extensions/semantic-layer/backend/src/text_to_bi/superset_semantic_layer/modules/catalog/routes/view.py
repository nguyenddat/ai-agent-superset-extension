from flask import abort, redirect
from flask_appbuilder import expose
from flask_login import current_user
from superset import appbuilder
from superset.views.base import BaseSupersetView

from ....core.security import can_view_semantic_layer


class SemanticLayerView(BaseSupersetView):
    route_base = "/semantic-layer"

    @expose("/")
    def page(self):
        """Serve Superset's SPA shell; the extension frontend renders the page content."""
        if not getattr(current_user, "is_authenticated", False):
            return redirect(appbuilder.get_url_for_login)
        if not can_view_semantic_layer():
            abort(403)
        return self.render_app_template()


appbuilder.add_view_no_menu(SemanticLayerView)
