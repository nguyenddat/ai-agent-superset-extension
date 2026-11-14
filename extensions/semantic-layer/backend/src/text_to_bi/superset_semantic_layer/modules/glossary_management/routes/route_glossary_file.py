from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db

from text_to_bi.superset_semantic_layer.common.utils.table_file import import_report
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import csrf_protected, require_admin
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables

from ..services.srv_glossary_file import apply_term_import, export_term_template, export_terms, preview_term_import

prefix = "/glossary/file"


class GlossaryFileRoutes(RouteMixin):
    # -------------------------READ---------------------------
    @expose(prefix, methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def export_glossary_file(self):
        """Mọi thuật ngữ thành file Excel theo mẫu, import đọc lại được."""
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, **export_terms())

    @expose(f"{prefix}/template", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def export_glossary_template(self):
        """File Excel mẫu để nhập thuật ngữ, có dòng ví dụ và sheet hướng dẫn."""
        require_admin()
        return self.response(200, **export_term_template())

    @expose(f"{prefix}/preview", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @handle_errors
    def preview_glossary_file(self):
        """Kết quả import từng dòng của file; không lưu gì."""
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, **import_report(preview_term_import(request.get_json(silent=True))))

    # -------------------------CREATE-------------------------
    @expose(f"{prefix}/import", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def import_glossary_file(self):
        """Tạo và cập nhật thuật ngữ của file thành bản nháp trong một transaction; một dòng lỗi thì không lưu gì."""
        require_admin()
        ensure_dictionary_tables()
        rows = apply_term_import(request.get_json(silent=True), current_user.id)
        db.session.commit()
        return self.response(200, **import_report(rows))
