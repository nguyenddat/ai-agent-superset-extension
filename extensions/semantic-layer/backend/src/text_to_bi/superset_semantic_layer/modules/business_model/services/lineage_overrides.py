from collections.abc import Container, Mapping
from typing import Any

EdgeKey = tuple[int, int, str]


def flipped_key(key: EdgeKey) -> EdgeKey:
    source_id, target_id, kind = key
    if kind not in ("flow", "relation"):
        return key
    return target_id, source_id, "relation" if kind == "flow" else "flow"


def match_override(key: EdgeKey, inferred: Container[EdgeKey], rows: Mapping[EdgeKey, Any]) -> Any | None:
    row = rows.get(key)
    if row is not None or key not in inferred:
        return row
    flipped = flipped_key(key)
    candidate = rows.get(flipped)
    if candidate is not None and flipped not in inferred and (candidate.is_hidden or not candidate.is_manual):
        return candidate
    return None
