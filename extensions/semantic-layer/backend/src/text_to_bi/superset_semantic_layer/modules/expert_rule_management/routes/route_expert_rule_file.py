from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from superset import db

from text_to_bi.superset_semantic_layer.common.utils.table_file import import_report
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import csrf_protected, require_admin

from ..exceptions import ExpertRuleValidationError
from ..services.srv_expert_rule_file import apply_rule_import, export_rule_template, export_rules, preview_rule_import

prefix = "/expert-rules/file"


class ExpertRuleFileRoutes(RouteMixin):
    # -------------------------READ---------------------------
    @expose(prefix, methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def export_expert_rule_file(self):
        """Mọi rule thành file Excel theo mẫu, import đọc lại được."""
        require_admin()
        return self.response(200, **export_rules())

    @expose(f"{prefix}/template", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def export_expert_rule_template(self):
        """File Excel mẫu để nhập rule, có dòng ví dụ và sheet hướng dẫn."""
        require_admin()
        return self.response(200, **export_rule_template())

    @expose(f"{prefix}/preview", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def preview_expert_rule_file(self):
        """Kết quả import từng dòng của file; không lưu gì."""
        require_admin()
        return self.response(200, **import_report(preview_rule_import(request.get_json(silent=True))))

    # -------------------------CREATE-------------------------
    @expose(f"{prefix}/import", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def import_expert_rule_file(self):
        """Tạo và cập nhật rule của file thành bản nháp trong một transaction; một dòng lỗi thì không lưu gì."""
        require_admin()
        # Repositories flush as they add rows, so a unique-name collision can surface inside the import too.
        try:
            rows = apply_rule_import(request.get_json(silent=True), current_user.id)
            db.session.commit()
        except IntegrityError as error:
            raise ExpertRuleValidationError("Không lưu được các rule trong file; tải lại trang rồi thử lại.") from error
        return self.response(200, **import_report(rows))
