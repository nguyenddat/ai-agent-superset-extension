from datetime import datetime, timezone
from typing import Any

from text_to_bi.superset_ai_agent.modules.semantic_layer.services.dataset_drafts import (
    create_dataset_draft,
    validate_dataset_draft,
)

from ..dependencies import dataset_proposal_repository
from ..exceptions import (
    AgentLadderValidationError,
    DatasetProposalNotFoundError,
    ProposalAlreadyReviewedError,
    TooManyPendingProposalsError,
)
from ..models import DatasetProposal

MAX_PENDING_PROPOSALS = 50


class DatasetProposalService:
    def __init__(self) -> None:
        self.proposals = dataset_proposal_repository()

    def propose(self, body: Any, actor_id: int, cookie: str, csrf: str) -> tuple[DatasetProposal, bool]:
        values = validate_dataset_draft(body, cookie, csrf)
        waiting = self.proposals.pending_with_fingerprint(values["sql_fingerprint"])
        if waiting is not None:
            return waiting, False
        if self.proposals.pending_count() >= MAX_PENDING_PROPOSALS:
            raise TooManyPendingProposalsError()
        proposal = DatasetProposal(
            **values, status="pending", proposer_id=actor_id, created_on=datetime.now(timezone.utc),
        )
        self.proposals.add(proposal, flush=False)
        return proposal, True

    def require_pending(self, proposal_id: int) -> DatasetProposal:
        proposal = self.proposals.read_for_update(proposal_id)
        if proposal is None:
            raise DatasetProposalNotFoundError()
        if proposal.status != "pending":
            raise ProposalAlreadyReviewedError()
        return proposal

    def update(self, proposal_id: int, body: Any, cookie: str, csrf: str) -> DatasetProposal:
        proposal = self.require_pending(proposal_id)
        values = validate_dataset_draft(
            {**body, "question": proposal.question} if isinstance(body, dict) else body, cookie, csrf,
        )
        for field, value in values.items():
            setattr(proposal, field, value)
        return proposal

    def reject(self, proposal_id: int, body: Any, actor_id: int) -> DatasetProposal:
        proposal = self.require_pending(proposal_id)
        reason = body.get("reason") if isinstance(body, dict) else None
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 512:
            raise AgentLadderValidationError("Nhập lý do từ chối, tối đa 512 ký tự.")
        proposal.status, proposal.review_note = "rejected", reason.strip()
        proposal.reviewer_id, proposal.reviewed_on = actor_id, datetime.now(timezone.utc)
        return proposal

    def create(self, proposal_id: int, actor_id: int, cookie: str, csrf: str) -> DatasetProposal:
        proposal = self.require_pending(proposal_id)
        body = {
            field: getattr(proposal, field) for field in ("name", "label", "description", "sql", "metric", "question")
        }
        body["creation_key"] = f"ai-agent:dataset-proposal:{proposal.id}"
        body["proposer_id"] = proposal.proposer_id
        dataset_id = create_dataset_draft(body, cookie, csrf)
        proposal.status, proposal.dataset_id = "created", dataset_id
        proposal.reviewer_id, proposal.reviewed_on = actor_id, datetime.now(timezone.utc)
        return proposal
