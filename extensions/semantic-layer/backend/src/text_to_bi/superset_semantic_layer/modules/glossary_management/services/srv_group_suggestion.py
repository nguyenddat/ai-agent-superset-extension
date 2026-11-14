import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from text_to_bi.superset_semantic_layer.common.utils.similarity import (
    NeighbourCluster,
    neighbour_clusters,
    similarity_matrix,
)
from text_to_bi.superset_semantic_layer.common.utils.type_formatter import compact_json

from ..dependencies import group_suggestion_dismissal_repository
from .srv_glossary_embedding import text_vectors

GLOSSARY_KIND = "glossary"
EXPERT_RULE_KIND = "expert_rule"
# The average cosine similarity at which items count as neighbours, by how their vectors were made. Measured on the
# sample glossary: with openai/text-embedding-3-small the rain terms score 0.75-0.79 with each other, "Độ ẩm" and
# "Nồm ẩm" 0.72, and unrelated terms at most 0.67; with TF-IDF the same pairs score 0.24-0.46 and unrelated ones at
# most 0.22. Another embedding model may need another threshold.
THRESHOLDS = {"embedding": 0.70, "tfidf": 0.25}
MAX_GROUPING_MEMBERS = 500
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class GroupingCandidate:
    """A term or rule as grouping compares it: its name, the text its meaning is read from, and its group."""

    id: int
    name: str
    text: str
    group_id: int | None


@dataclass(frozen=True)
class GroupingChoice:
    """What an administrator applies: the members to move, into an existing group or a new one with this name."""

    member_ids: list[int]
    group_id: int | None
    group_name: str | None


# -------------------------READ---------------------------
def suggest_groups(kind: str, candidates: list[GroupingCandidate], group_names: dict[int, str]) -> dict[str, Any]:
    """Gợi ý nhóm cho các mục chưa phân nhóm có nghĩa gần nhau, bỏ các gợi ý quản trị viên đã bỏ qua.

    Each suggestion puts members in an existing group they are close to, or in a new group named after its most
    central member, and shows how similar each member is to the rest and to its closest neighbour.
    """
    vectors = text_vectors([candidate.text for candidate in candidates])
    threshold = THRESHOLDS[vectors.method]
    similarity = similarity_matrix(vectors.vectors)
    dismissed = group_suggestion_dismissal_repository().read_fingerprints(kind)
    suggestions = [
        suggestion
        for cluster in neighbour_clusters([candidate.group_id for candidate in candidates], similarity, threshold)
        if (suggestion := _suggestion(cluster, candidates, similarity, group_names))["fingerprint"] not in dismissed
    ]
    suggestions.sort(key=lambda suggestion: (-suggestion["similarity"], suggestion["proposed_name"].casefold()))
    return {"method": vectors.method, "model": vectors.model, "threshold": threshold, "suggestions": suggestions}


def suggestion_fingerprint(group_id: int | None, member_ids: Sequence[int]) -> str:
    """Định danh của gợi ý: nhóm đích (None nếu nhóm mới) và các mục được chuyển."""
    return hashlib.sha256(compact_json({"group_id": group_id, "member_ids": sorted(member_ids)}).encode()).hexdigest()


# -------------------------CREATE-------------------------
def dismiss_suggestion(kind: str, payload: Any, actor_id: int, invalid: type[Exception]) -> str:
    """Ghi nhận gợi ý bị bỏ qua để không gợi ý lại; trả về fingerprint."""
    fingerprint = payload.get("fingerprint") if isinstance(payload, dict) else None
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise invalid("Gợi ý gom nhóm không hợp lệ.")
    repository = group_suggestion_dismissal_repository()
    if fingerprint not in repository.read_fingerprints(kind):
        values = {
            "kind": kind,
            "fingerprint": fingerprint,
            "dismissed_by": actor_id,
            "dismissed_at": datetime.now(timezone.utc),
        }
        repository.create(values, flush=False)
    return fingerprint


# -------------------------CHECK--------------------------
def grouping_choice(payload: Any, invalid: type[Exception]) -> GroupingChoice:
    """Các mục quản trị viên giữ lại từ gợi ý và nhóm đích: `group_id` nhóm có sẵn, hoặc `group_name` nhóm mới."""
    if not isinstance(payload, dict):
        raise invalid("Gợi ý gom nhóm không hợp lệ.")
    member_ids = payload.get("member_ids")
    if (
        not isinstance(member_ids, list)
        or not member_ids
        or len(member_ids) > MAX_GROUPING_MEMBERS
        or any(isinstance(member_id, bool) or not isinstance(member_id, int) for member_id in member_ids)
    ):
        raise invalid("Chọn ít nhất một mục để gom nhóm.")
    member_ids = list(dict.fromkeys(member_ids))
    group_id = payload.get("group_id")
    if group_id is not None:
        if isinstance(group_id, bool) or not isinstance(group_id, int):
            raise invalid("Nhóm không hợp lệ.")
        return GroupingChoice(member_ids, group_id, None)
    group_name = payload.get("group_name")
    if not isinstance(group_name, str) or not group_name.strip():
        raise invalid("Nhập tên nhóm mới.")
    return GroupingChoice(member_ids, None, group_name)


# -------------------------HELPERS------------------------
def _suggestion(
    cluster: NeighbourCluster,
    candidates: list[GroupingCandidate],
    similarity: list[list[float]],
    group_names: dict[int, str],
) -> dict[str, Any]:
    together = cluster.member_indexes + cluster.anchor_indexes
    members = []
    for index in cluster.member_indexes:
        others = [other for other in together if other != index]
        closest = max(others, key=lambda other: similarity[index][other])
        members.append(
            {
                "id": candidates[index].id,
                "name": candidates[index].name,
                "similarity": _rounded(sum(similarity[index][other] for other in others) / len(others)),
                "closest": {
                    "id": candidates[closest].id,
                    "name": candidates[closest].name,
                    "similarity": _rounded(similarity[index][closest]),
                },
            }
        )
    members.sort(key=lambda member: -member["similarity"])
    if cluster.group_id is None:
        # The member most similar to the others names the new group; the administrator may rename it.
        central = max(
            cluster.member_indexes,
            key=lambda index: (sum(similarity[index][other] for other in cluster.member_indexes), -index),
        )
        group, proposed_name = None, candidates[central].name
    else:
        name = group_names.get(cluster.group_id, f"#{cluster.group_id}")
        group, proposed_name = {"id": cluster.group_id, "name": name}, name
    return {
        "fingerprint": suggestion_fingerprint(cluster.group_id, [member["id"] for member in members]),
        "group": group,
        "proposed_name": proposed_name,
        "similarity": _rounded(sum(member["similarity"] for member in members) / len(members)),
        "members": members,
        "group_members": [_reference(candidates[index]) for index in cluster.anchor_indexes],
    }


def _reference(candidate: GroupingCandidate) -> dict[str, Any]:
    return {"id": candidate.id, "name": candidate.name}


def _rounded(value: float) -> float:
    return round(value, 3)
