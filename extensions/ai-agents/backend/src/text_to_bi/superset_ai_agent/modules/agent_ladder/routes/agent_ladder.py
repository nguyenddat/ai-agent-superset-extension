from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_ai_agent.common.public import public_payload
from text_to_bi.superset_ai_agent.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_ai_agent.core.security import csrf_protected, require_admin, require_semantic_layer_query
from text_to_bi.superset_ai_agent.migrations import ensure_agent_tables
from text_to_bi.superset_ai_agent.modules.semantic_layer.services.dataset_drafts import dataset_sources

from ..services.proposals import DatasetProposalService
from ..utils.serializer import serialize_proposal


@api(id="text_to_bi_agent_ladder_api", name="AI Agent dataset proposals", resource_name="agent-ladder")
class AgentLadderAPI(RestApi):
    class_permission_name = "text_to_bi_chat_api"

    @expose("/dataset-proposals", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_proposals(self):
        require_admin()
        ensure_agent_tables()
        proposals = DatasetProposalService().proposals.newest_first()
        proposals.sort(key=lambda proposal: proposal.status != "pending")
        sources = dataset_sources(request.headers.get("Cookie", ""))
        return self.response(200, **public_payload({'proposals': [serialize_proposal(proposal, sources) for proposal in proposals]}))

    @expose("/dataset-proposals", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def propose_dataset(self):
        require_semantic_layer_query()
        ensure_agent_tables()
        proposal, created = DatasetProposalService().propose(request.get_json(silent=True), current_user.id, request.headers.get("Cookie", ""), request.headers.get("X-CSRFToken", ""))
        sources = dataset_sources(request.headers.get("Cookie", ""))
        db.session.commit()
        return self.response(201 if created else 200, **public_payload({'proposal': serialize_proposal(proposal, sources)}))

    @expose("/dataset-proposals/<int:proposal_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_proposal(self, proposal_id: int):
        require_admin()
        ensure_agent_tables()
        proposal = DatasetProposalService().update(proposal_id, request.get_json(silent=True), request.headers.get("Cookie", ""), request.headers.get("X-CSRFToken", ""))
        sources = dataset_sources(request.headers.get("Cookie", ""))
        db.session.commit()
        return self.response(200, **public_payload({'proposal': serialize_proposal(proposal, sources)}))

    @expose("/dataset-proposals/<int:proposal_id>/reject", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def reject_proposal(self, proposal_id: int):
        require_admin()
        ensure_agent_tables()
        proposal = DatasetProposalService().reject(proposal_id, request.get_json(silent=True), current_user.id)
        sources = dataset_sources(request.headers.get("Cookie", ""))
        db.session.commit()
        return self.response(200, **public_payload({'proposal': serialize_proposal(proposal, sources)}))

    @expose("/dataset-proposals/<int:proposal_id>/create", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_proposal(self, proposal_id: int):
        require_admin()
        ensure_agent_tables()
        proposal = DatasetProposalService().create(proposal_id, current_user.id, request.headers.get("Cookie", ""), request.headers.get("X-CSRFToken", ""))
        sources = dataset_sources(request.headers.get("Cookie", ""))
        db.session.commit()
        return self.response(200, **public_payload({'proposal': serialize_proposal(proposal, sources)}))
