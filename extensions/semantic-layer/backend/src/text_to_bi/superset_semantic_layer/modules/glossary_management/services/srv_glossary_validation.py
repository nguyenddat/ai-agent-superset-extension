import hashlib
import json
from typing import Any

from ..exceptions import GlossaryValidationError

MAX_NAME_LENGTH = 255
MAX_DEFINITION_LENGTH = 10_000
MAX_SYNONYMS = 50
MAX_REASON_LENGTH = 512
LINK_KINDS = {"dataset", "column", "metric"}
CONTENT_FIELDS = {"canonical_name", "definition", "synonyms", "steward_id", "links"}


def normalized_name(value: str) -> str:
    """Tên so sánh không phân biệt hoa thường và khoảng trắng."""
    return " ".join(value.split()).casefold()


def expected_revision_of(payload: Any) -> int:
    """Số phiên bản client đã đọc; thay đổi phải còn khớp với nó."""
    expected_revision = payload.get("expected_revision") if isinstance(payload, dict) else None
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise GlossaryValidationError("expected_revision is required.")
    return expected_revision


def review_reason(payload: Any) -> str | None:
    """Ghi chú khi duyệt hoặc thu hồi, đã cắt khoảng trắng; rỗng là không có."""
    reason = payload.get("reason") if isinstance(payload, dict) else None
    if reason is None:
        return None
    if not isinstance(reason, str) or len(reason) > MAX_REASON_LENGTH:
        raise GlossaryValidationError("Invalid review reason.")
    return reason.strip() or None


def group_id_of(payload: Any) -> int | None:
    """Nhóm request đặt thuật ngữ vào; null là bỏ khỏi mọi nhóm."""
    group_id = payload.get("group_id") if isinstance(payload, dict) else None
    if group_id is not None and (isinstance(group_id, bool) or not isinstance(group_id, int)):
        raise GlossaryValidationError("Nhóm thuật ngữ không hợp lệ.")
    return group_id


def normalize_group_payload(payload: Any) -> dict[str, Any]:
    """Tên nhóm (duy nhất, không phân biệt hoa thường và khoảng trắng) và mô tả tùy chọn."""
    if not isinstance(payload, dict) or set(payload) - {"name", "description"}:
        raise GlossaryValidationError("Nhóm thuật ngữ chỉ có tên và mô tả.")
    name = payload.get("name")
    if not isinstance(name, str) or not (name := " ".join(name.split())):
        raise GlossaryValidationError("Nhập tên nhóm thuật ngữ.")
    if len(name) > MAX_NAME_LENGTH:
        raise GlossaryValidationError("Tên nhóm thuật ngữ quá dài.")
    description = payload.get("description")
    if description is not None and not isinstance(description, str):
        raise GlossaryValidationError("Mô tả nhóm thuật ngữ không hợp lệ.")
    description = (description or "").strip() or None
    if description is not None and len(description) > MAX_DEFINITION_LENGTH:
        raise GlossaryValidationError("Mô tả nhóm thuật ngữ quá dài.")
    return {"name": name, "normalized_name": normalized_name(name), "description": description}


def normalize_glossary_payload(payload: Any) -> dict[str, Any]:
    """Từ chối trường lạ và chuẩn hóa nội dung thuật ngữ trước khi lưu."""
    if not isinstance(payload, dict) or set(payload) - CONTENT_FIELDS - {"expected_revision", "group_id"}:
        raise GlossaryValidationError("Unsupported glossary fields.")
    name = _required_text(payload.get("canonical_name"), "canonical_name", MAX_NAME_LENGTH)
    definition = _required_text(payload.get("definition"), "definition", MAX_DEFINITION_LENGTH)
    synonyms = payload.get("synonyms", [])
    if not isinstance(synonyms, list) or len(synonyms) > MAX_SYNONYMS:
        raise GlossaryValidationError("synonyms must be a bounded array.")
    name_key = normalized_name(name)
    clean_synonyms: list[str] = []
    seen = {name_key}
    for synonym in synonyms:
        clean = _required_text(synonym, "synonym", MAX_NAME_LENGTH)
        synonym_key = normalized_name(clean)
        if synonym_key in seen:
            if synonym_key == name_key:
                raise GlossaryValidationError("A synonym cannot duplicate the canonical name.")
            continue
        seen.add(synonym_key)
        clean_synonyms.append(clean)
    links = payload.get("links")
    if not isinstance(links, list) or not links:
        raise GlossaryValidationError("At least one glossary link is required.")
    for link in links:
        if not isinstance(link, dict) or set(link) - {"kind", "dataset_id", "column_name", "metric_id"}:
            raise GlossaryValidationError("Invalid glossary link.")
        dataset_id = link.get("dataset_id")
        if link.get("kind") not in LINK_KINDS or isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
            raise GlossaryValidationError("Invalid glossary link.")
    steward_id = payload.get("steward_id")
    if steward_id is not None and (isinstance(steward_id, bool) or not isinstance(steward_id, int)):
        raise GlossaryValidationError("steward_id must be a user id.")
    return {
        "canonical_name": name,
        "normalized_name": name_key,
        "definition": definition,
        "synonyms": clean_synonyms,
        "steward_id": steward_id,
        "links": links,
    }


def content_hash(values: dict[str, Any]) -> str:
    """Hash nội dung một bản, để quy tắc chuyên gia biết khi thuật ngữ đổi nghĩa."""
    content = {key: values.get(key) for key in ("canonical_name", "definition", "synonyms", "links")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _required_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not (result := " ".join(value.split())):
        raise GlossaryValidationError(f"{field} must be a non-empty string.")
    if len(result) > limit:
        raise GlossaryValidationError(f"{field} is too long.")
    return result
