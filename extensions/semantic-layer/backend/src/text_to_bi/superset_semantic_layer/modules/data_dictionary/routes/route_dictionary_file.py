from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset import db

from text_to_bi.superset_semantic_layer.common.utils.table_file import import_report
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import csrf_protected, require_admin
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables

from ..services.srv_dictionary_file import (
    apply_dictionary_import,
    export_dictionary,
    export_dictionary_template,
    preview_dictionary_import,
)


class DataDictionaryFileRoutes(RouteMixin):
    # -------------------------READ---------------------------
    @expose("/dictionary/file", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def export_dictionary_file(self):
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, **export_dictionary())

    @expose("/dictionary/file/template", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def export_dictionary_file_template(self):
        require_admin()
        return self.response(200, **export_dictionary_template())

    @expose("/dictionary/file/preview", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def preview_dictionary_file(self):
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, **import_report(preview_dictionary_import(request.get_json(silent=True))))

    # -------------------------UPDATE-------------------------
    @expose("/dictionary/file/import", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def import_dictionary_file(self):
        require_admin()
        ensure_dictionary_tables()
        rows = apply_dictionary_import(request.get_json(silent=True))
        db.session.commit()
        return self.response(200, **import_report(rows))
