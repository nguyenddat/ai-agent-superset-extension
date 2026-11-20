from collections.abc import Callable
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from superset import db

from text_to_bi.superset_semantic_layer.common.public import public_payload
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.exceptions import DatasetAccessError
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import (
    csrf_protected,
    require_admin,
    require_semantic_layer_query,
    require_semantic_layer_view,
    second_reviewer_required,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import user_names

from ..exceptions import ExpertRuleValidationError
from ..models import ExpertRuleRevision
from ..services.srv_expert_rule import ExpertRuleService
from ..services.srv_expert_rule_event import ExpertRuleEventService
from ..services.srv_expert_rule_group import ExpertRuleGroupService
from ..services.srv_expert_rule_link import rule_options
from ..services.srv_expert_rule_validation import expected_revision_of, group_id_of
from ..utils.util_serializer import (
    serialize_discovered_rule,
    serialize_expert_rule,
    serialize_expert_rule_events,
    serialize_expert_rule_group,
    serialize_expert_rule_review_entry,
    serialize_group_reference,
)

# Tables are provisioned only by the bootstrap and migration gate; these request paths never issue metadata DDL.
prefix = "/expert-rules"


class ExpertRuleRoutes(RouteMixin):
    # -------------------------READ---------------------------
    @expose(prefix, methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_expert_rules(self):
        require_semantic_layer_view()
        user_name = user_names()
        rules_service = ExpertRuleService()
        entries = rules_service.read_for_review()
        links = rules_service.links.read_for_revisions([revision.id for _, revision in entries])
        rules = [
            serialize_expert_rule_review_entry(rule, revision, links.get(revision.id, []), user_name)
            for rule, revision in entries
        ]
        rules.sort(key=lambda item: item["name"].casefold())
        return self.response(
            200,
            rules=rules,
            groups=[serialize_expert_rule_group(group) for group in ExpertRuleGroupService().read_all()],
            current_user_id=current_user.id,
            require_second_reviewer=second_reviewer_required(),
        )

    @expose(f"{prefix}/options", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_expert_rule_options(self):
        require_semantic_layer_view()
        return self.response(200, datasets=rule_options())

    @expose(f"{prefix}/discover", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_discoverable_expert_rules(self):
        require_semantic_layer_query()
        discovered = ExpertRuleService().read_discoverable()
        return self.response(
            200, **public_payload({"rules": [serialize_discovered_rule(*item) for item in discovered]})
        )

    @expose(f"{prefix}/<int:rule_id>/audit", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_expert_rule_events(self, rule_id: int):
        require_semantic_layer_view()
        if not ExpertRuleService().read_rule_readable(rule_id):
            raise DatasetAccessError()
        events = ExpertRuleEventService().read_history(rule_id)
        return self.response(200, audit=serialize_expert_rule_events(events, user_names()))

    # -------------------------CREATE-------------------------
    @expose(prefix, methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_expert_rule(self):
        require_admin()
        payload = _body()
        return self.response(201, rule=_committed(lambda: ExpertRuleService().create(payload, current_user.id)))

    # -------------------------UPDATE-------------------------
    @expose(f"{prefix}/<int:rule_id>/draft", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_expert_rule(self, rule_id: int):
        require_admin()
        payload = _body()
        rules = ExpertRuleService()
        rules.require_current(rule_id)
        revision = _committed(
            lambda: rules.update(rule_id, payload, expected_revision_of(payload), current_user.id)
        )
        return self.response(200, rule=revision)

    @expose(f"{prefix}/<int:rule_id>/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_expert_rule(self, rule_id: int):
        require_admin()
        payload = _body()
        rules = ExpertRuleService()
        rules.require_current(rule_id)
        revision = _committed(
            lambda: rules.approve(
                rule_id,
                expected_revision_of(payload),
                current_user.id,
                payload.get("reason"),
                second_reviewer_required(),
            )
        )
        return self.response(200, rule=revision)

    @expose(f"{prefix}/<int:rule_id>/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_expert_rule(self, rule_id: int):
        require_admin()
        payload = _body()
        rules = ExpertRuleService()
        rules.require_current(rule_id)
        revision = _committed(
            lambda: rules.revoke(rule_id, expected_revision_of(payload), current_user.id, payload.get("reason"))
        )
        return self.response(200, rule=revision)

    @expose(f"{prefix}/<int:rule_id>/group", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def move_expert_rule(self, rule_id: int):
        require_admin()
        payload = _body()
        if "group_id" not in payload or set(payload) - {"group_id"}:
            raise ExpertRuleValidationError("Cần cung cấp group_id; dùng null để bỏ nhóm.")
        group_id = group_id_of(payload)
        rule = ExpertRuleGroupService().move_rule(rule_id, group_id, current_user.id)
        db.session.commit()
        return self.response(200, rule_id=rule.id, group=serialize_group_reference(rule.group))


def _body() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ExpertRuleValidationError("Request body must be an object.")
    return payload


def _committed(save: Callable[[], ExpertRuleRevision]) -> dict[str, Any]:
    try:
        revision = save()
        db.session.commit()
    except IntegrityError as error:
        raise ExpertRuleValidationError("Could not save the expert rule.") from error
    return serialize_expert_rule(revision)
