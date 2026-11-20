from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db

from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import csrf_protected, require_admin

from ..services.srv_expert_rule_group import ExpertRuleGroupService
from ..utils.util_serializer import serialize_expert_rule_group

prefix = "/expert-rules/groups"
suggestion_prefix = "/expert-rules/group-suggestions"


class ExpertRuleGroupRoutes(RouteMixin):
    # -------------------------CREATE-------------------------
    @expose(prefix, methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_expert_rule_group(self):
        require_admin()
        group = ExpertRuleGroupService().create(request.get_json(silent=True))
        db.session.commit()
        return self.response(201, group=serialize_expert_rule_group(group))

    # -------------------------UPDATE-------------------------
    @expose(f"{prefix}/<int:group_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_expert_rule_group(self, group_id: int):
        require_admin()
        group = ExpertRuleGroupService().update(group_id, request.get_json(silent=True))
        db.session.commit()
        return self.response(200, group=serialize_expert_rule_group(group))

    # -------------------------DELETE-------------------------
    @expose(f"{prefix}/<int:group_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_expert_rule_group(self, group_id: int):
        require_admin()
        moved_rule_ids = ExpertRuleGroupService().delete(group_id, current_user.id)
        db.session.commit()
        return self.response(200, moved_rule_ids=moved_rule_ids)

    # -------------------------SUGGESTION---------------------
    @expose(suggestion_prefix, methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_expert_rule_group_suggestions(self):
        require_admin()
        suggestions = ExpertRuleGroupService().suggest()
        return self.response(200, **suggestions)

    @expose(f"{suggestion_prefix}/apply", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def apply_expert_rule_group_suggestion(self):
        require_admin()
        payload = request.get_json(silent=True)
        group, moved_rule_ids = ExpertRuleGroupService().apply_suggestion(payload, current_user.id)
        db.session.commit()
        return self.response(200, group=serialize_expert_rule_group(group), moved_rule_ids=moved_rule_ids)

    @expose(f"{suggestion_prefix}/dismiss", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def dismiss_expert_rule_group_suggestion(self):
        require_admin()
        fingerprint = ExpertRuleGroupService.dismiss_suggestion(request.get_json(silent=True), current_user.id)
        db.session.commit()
        return self.response(200, fingerprint=fingerprint)
