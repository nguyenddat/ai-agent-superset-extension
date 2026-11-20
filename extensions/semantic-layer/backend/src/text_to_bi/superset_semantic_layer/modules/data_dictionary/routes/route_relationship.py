from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db

from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import csrf_protected, require_admin
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.superset import requires_dataset

from ..services.srv_relationship import RelationshipService
from ..utils.util_serializer import serialize_relationship_contract, serialize_revoked_contract

prefix = "/dataset/<int:dataset_id>/relationships"


class RelationshipRoutes(RouteMixin):
    # -------------------------CREATE-------------------------
    @expose(f"{prefix}/<int:column_id>/contract/candidate", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_relationship_contract_candidate(self, dataset_id: int, column_id: int):
        require_admin()
        ensure_dictionary_tables()
        body = request.get_json(silent=True)
        origin = body.get("source") if isinstance(body, dict) else None
        contract, source, target = RelationshipService().create_candidate(
            dataset_id, column_id, origin, current_user.id
        )
        db.session.commit()
        return self.response(201, contract=serialize_relationship_contract(contract, source, target))

    @expose(f"{prefix}/apply", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_dataset
    def apply_relationship_suggestion(self, dataset: Any):
        require_admin()
        ensure_dictionary_tables()
        relationship = RelationshipService().apply_suggestion(dataset, request.get_json(silent=True), current_user.id)
        db.session.commit()
        return self.response(201, relationship=relationship)

    # -------------------------READ---------------------------
    @expose(prefix, methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    @requires_dataset
    def list_relationships(self, dataset: Any):
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, **RelationshipService().read_all(dataset, request.args.get("suggest") == "1"))

    # -------------------------UPDATE-------------------------
    @expose(f"{prefix}/<int:column_id>/verify", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def verify_relationship(self, dataset_id: int, column_id: int):
        require_admin()
        ensure_dictionary_tables()
        verified = RelationshipService().verify(dataset_id, column_id)
        if verified is None:
            # A failed recheck removes approval even when the warehouse query could not finish.
            db.session.commit()
            return self.response_500(message="Could not run the relationship check on the database.")
        db.session.commit()
        return self.response(200, contract=serialize_relationship_contract(*verified))

    @expose(f"{prefix}/<int:column_id>/contract/approve", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def approve_relationship_contract(self, dataset_id: int, column_id: int):
        require_admin()
        ensure_dictionary_tables()
        contract, source, target = RelationshipService().approve(dataset_id, column_id, current_user.id)
        db.session.commit()
        return self.response(200, contract=serialize_relationship_contract(contract, source, target))

    @expose(f"{prefix}/<int:column_id>/contract/revoke", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def revoke_relationship_contract(self, dataset_id: int, column_id: int):
        require_admin()
        ensure_dictionary_tables()
        contract, entry = RelationshipService().revoke(
            dataset_id, column_id, request.args.get("contract_id", type=int), current_user.id
        )
        db.session.commit()
        return self.response(200, contract=serialize_revoked_contract(contract, entry))
