from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Any

from ..exceptions import ContradictionValidationError
from .srv_contradiction_detection import SEMANTIC_KINDS, Finding

MAX_REASON_LENGTH = 512


def finding_values(finding: Finding) -> dict[str, Any]:
    """What a stored contradiction keeps of a finding; the items carry their names as they were when found."""
    return {
        "kind": finding.kind,
        "pair_key": finding.pair_key,
        "items": [asdict(item) for item in finding.items],
        "fingerprint": finding.fingerprint,
        "evidence": list(finding.evidence),
        "explanation": finding.explanation,
    }


def reconcile(
    stored: list[Any], findings: list[Finding], new_row: Callable[[dict[str, Any]], Any], now: datetime
) -> tuple[list[Any], list[Any]]:
    """Bring the stored contradictions in line with a check's findings; returns the rows to add and to delete.

    A finding already stored with the same fingerprint keeps its state, so a dismissal holds while both items are
    unchanged. A changed fingerprint means an item changed: the row opens again with the new evidence. A stored row the
    check no longer finds was resolved by an edit and is deleted.
    """
    by_key = {row.pair_key: row for row in stored}
    added, found_keys = [], set()
    for finding in findings:
        values = finding_values(finding)
        found_keys.add(finding.pair_key)
        row = by_key.get(finding.pair_key)
        if row is None:
            added.append(new_row({**values, "status": "open", "detected_at": now}))
            continue
        if row.fingerprint != finding.fingerprint:
            row.status, row.detected_at = "open", now
            row.dismiss_reason, row.dismissed_by, row.dismissed_at = None, None, None
        for name, value in values.items():
            setattr(row, name, value)
    return added, [row for row in stored if row.pair_key not in found_keys]


def dismissal_reason(payload: Any) -> str:
    """Why an administrator accepts a contradiction as it is: required, trimmed, at most 512 characters."""
    reason = payload.get("reason") if isinstance(payload, dict) else None
    if not isinstance(reason, str) or not (reason := " ".join(reason.split())):
        raise ContradictionValidationError("Nhập lý do bỏ qua mâu thuẫn.")
    if len(reason) > MAX_REASON_LENGTH:
        raise ContradictionValidationError("Lý do bỏ qua dài quá 512 ký tự.")
    return reason


def found_by(kind: str) -> str:
    """`ai` for a kind the AI model judges, `rule` for one a rule-based check finds."""
    return "ai" if kind in SEMANTIC_KINDS else "rule"
