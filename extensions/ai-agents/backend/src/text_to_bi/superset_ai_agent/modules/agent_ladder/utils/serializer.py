from typing import Any

from text_to_bi.superset_ai_agent.common.utils.type_formatter import iso_datetime
from text_to_bi.superset_ai_agent.modules.superset.services.users import user_names

from ..models import DatasetProposal


def serialize_proposal(proposal: DatasetProposal, sources: list[dict[str, Any]]) -> dict[str, Any]:
    user_name = user_names()
    return {
        **{
            field: getattr(proposal, field)
            for field in (
                "id", "name", "label", "description", "sql", "metric", "question", "status", "review_note",
                "dataset_id",
            )
        },
        "sources": [
            {"id": source["id"], "name": source["name"]} for source in sources
            if source["id"] in (proposal.source_dataset_ids or [])
        ],
        "proposer_name": user_name(proposal.proposer_id),
        "reviewer_name": user_name(proposal.reviewer_id),
        "created_on": iso_datetime(proposal.created_on),
        "reviewed_on": iso_datetime(proposal.reviewed_on),
    }
