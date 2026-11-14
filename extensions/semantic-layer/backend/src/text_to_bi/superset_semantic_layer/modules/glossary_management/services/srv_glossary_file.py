from dataclasses import dataclass
from typing import Any

from superset import security_manager

from text_to_bi.superset_semantic_layer.common.exceptions import SemanticLayerError
from text_to_bi.superset_semantic_layer.common.utils.table_file import (
    ImportRow,
    TemplateColumn,
    dataset_named,
    join_list,
    read_table,
    refusal_message,
    split_list,
    write_table,
    write_template,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import (
    business_datasets_by_name,
    get_dataset,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_user import get_user

from ..dependencies import (
    glossary_group_repository,
    glossary_link_repository,
    glossary_revision_repository,
    glossary_term_repository,
)
from ..exceptions import GlossaryValidationError
from .srv_glossary_group import GlossaryGroupService
from .srv_glossary_link import metric_approved, validated_links
from .srv_glossary_term import GlossaryTermService, checked_term_content
from .srv_glossary_validation import normalize_group_payload, normalized_name

TERM_FILE_NAME = "thuat-ngu"
LINK_FORMAT = "dataset:<bảng>, column:<bảng>.<cột> hoặc metric:<bảng>.<metric>"
TERM_COLUMNS = (
    TemplateColumn("canonical_name", True, "Tên thuật ngữ, tối đa 255 ký tự; khớp thuật ngữ đã có không phân biệt hoa thường, khoảng trắng.", "Nhiệt độ trung bình"),
    TemplateColumn("definition", True, "Định nghĩa nghiệp vụ, tối đa 10.000 ký tự.", "Trung bình nhiệt độ quan sát được trong khoảng thời gian, đơn vị °C."),
    TemplateColumn("synonyms", False, "Từ đồng nghĩa, cách nhau bằng ;", "nhiệt độ TB; nhiệt độ bình quân"),
    TemplateColumn("group", False, "Tên nhóm; trống là chưa phân nhóm, nhóm chưa có sẽ được tạo.", "Thời tiết"),
    TemplateColumn("steward", False, "Tên đăng nhập Superset của người phụ trách.", "admin"),
    TemplateColumn("links", True, f"Ít nhất một liên kết, cách nhau bằng ;: {LINK_FORMAT}.", "column:tb_gia_tri_quan_sat.gia_tri_so"),
)
# The editor's validation answers in English; the preview shows these in Vietnamese.
TERM_MESSAGES = {
    "canonical_name must be a non-empty string.": "Thiếu tên thuật ngữ.",
    "canonical_name is too long.": "Tên thuật ngữ quá dài (tối đa 255 ký tự).",
    "definition must be a non-empty string.": "Thiếu định nghĩa.",
    "definition is too long.": "Định nghĩa quá dài (tối đa 10.000 ký tự).",
    "synonym is too long.": "Có từ đồng nghĩa quá dài (tối đa 255 ký tự).",
    "synonyms must be a bounded array.": "Quá nhiều từ đồng nghĩa (tối đa 50).",
    "A synonym cannot duplicate the canonical name.": "Từ đồng nghĩa trùng với tên thuật ngữ.",
    "At least one glossary link is required.": "Cần ít nhất một liên kết.",
    "Invalid glossary link.": "Liên kết không hợp lệ.",
    "Duplicate glossary link.": "Có liên kết bị lặp.",
    "A glossary term may link only approved metrics.": "Thuật ngữ chỉ được liên kết metric đã duyệt.",
}


@dataclass
class TermPlan:
    """How a row is applied: the editor payload, the term it updates and the group the import creates for it."""

    payload: dict[str, Any]
    term_id: int | None = None
    revision_number: int | None = None
    content_changed: bool = True
    new_group: str | None = None


# -------------------------READ---------------------------
def export_term_template() -> dict[str, str]:
    """File Excel mẫu để nhập thuật ngữ: tiêu đề, một dòng ví dụ và sheet hướng dẫn."""
    return write_template(TERM_COLUMNS, [[column.example for column in TERM_COLUMNS]], TERM_FILE_NAME, GlossaryValidationError)


def export_terms() -> dict[str, str]:
    """Bản hiện tại của mọi thuật ngữ thành file Excel theo mẫu, import lại được nguyên vẹn."""
    revisions, links = glossary_revision_repository(), glossary_link_repository()
    rows = []
    for term in glossary_term_repository().read_all():
        revision = revisions.read_current(term.id)
        if revision is None:
            continue
        steward = get_user(term.steward_id) if term.steward_id is not None else None
        rows.append(
            [
                term.canonical_name,
                revision.definition,
                join_list(revision.synonyms or []),
                term.group.name if term.group else "",
                steward.username if steward else "",
                join_list(_link_token(link) for link in links.read_by_revision(revision.id)),
            ]
        )
    return write_table(TERM_COLUMNS, rows, TERM_FILE_NAME, GlossaryValidationError)


def preview_term_import(payload: Any) -> list[ImportRow]:
    """Kết quả import từng dòng của file, kiểm tra như trình soạn; không lưu gì."""
    datasets = business_datasets_by_name()
    first_rows: dict[str, int] = {}
    result = []
    for number, cells in read_table(payload, TERM_COLUMNS, GlossaryValidationError):
        item = ImportRow(row=number, key=cells["canonical_name"])
        name_key = normalized_name(cells["canonical_name"])
        try:
            if name_key and name_key in first_rows:
                raise GlossaryValidationError(f"Thuật ngữ trùng với dòng {first_rows[name_key]}.")
            first_rows.setdefault(name_key, number)
            _plan_term(item, cells, datasets)
        except SemanticLayerError as error:
            item.action, item.message, item.changes = "error", TERM_MESSAGES.get(str(error), str(error)), []
        result.append(item)
    return result


# -------------------------CREATE-------------------------
def apply_term_import(payload: Any, actor_id: int) -> list[ImportRow]:
    """Tạo và cập nhật thuật ngữ của file thành bản nháp chờ duyệt; một dòng lỗi thì không lưu gì.

    An approved term keeps serving its approved revision until the draft is approved. A row that only changes the
    group moves the term without review. The caller commits once.
    """
    rows = preview_term_import(payload)
    refusal = refusal_message(rows)
    if refusal:
        raise GlossaryValidationError(refusal)
    terms, groups = GlossaryTermService(), GlossaryGroupService()
    created_groups: dict[str, int] = {}
    for item in rows:
        plan = item.plan
        if item.action == "unchanged":
            continue
        term_payload = dict(plan.payload)
        if plan.new_group is not None:
            group_key = normalized_name(plan.new_group)
            if group_key not in created_groups:
                created_groups[group_key] = groups.create({"name": plan.new_group}).id
            term_payload["group_id"] = created_groups[group_key]
        if plan.term_id is None:
            terms.create(term_payload, actor_id)
        elif plan.content_changed:
            terms.update(plan.term_id, term_payload, plan.revision_number, actor_id)
        else:
            groups.move_term(plan.term_id, term_payload["group_id"], actor_id)
    return rows


# -------------------------HELPERS------------------------
def _plan_term(item: ImportRow, cells: dict[str, str], datasets: dict[str, list[Any]]) -> None:
    term = glossary_term_repository().read_by_normalized_name(normalized_name(cells["canonical_name"]))
    revisions = glossary_revision_repository()
    revision = revisions.read_current(term.id) if term else None
    stored_synonyms = list(revision.synonyms or []) if revision else []
    term_payload = {
        "canonical_name": cells["canonical_name"],
        "definition": cells["definition"],
        "synonyms": split_list(cells["synonyms"]) if "synonyms" in cells else stored_synonyms,
        "steward_id": _steward_id(cells["steward"]) if "steward" in cells else (term.steward_id if term else None),
        "links": [_link(token, datasets) for token in split_list(cells["links"])],
    }
    values = checked_term_content(term_payload)
    stored_links = glossary_link_repository().read_by_revision(revision.id) if revision else []
    stored_metric_keys = {(link.dataset_id, link.metric_id) for link in stored_links if link.kind == "metric"}
    # A metric the term already links stays acceptable while the row leaves the term's content unchanged, so a file
    # exported unchanged imports back even after that metric's contract stopped being approved.
    unapproved_metrics = []

    def metric_is_approved(dataset: Any, metric: Any) -> bool:
        if metric_approved(dataset, metric):
            return True
        unapproved_metrics.append(metric)
        return (dataset.id, metric.id) in stored_metric_keys

    links = validated_links(values["links"], get_dataset, metric_is_approved)
    plan = TermPlan(term_payload)
    if "group" in cells:
        group = None
        if cells["group"]:
            group = glossary_group_repository().read_by_normalized_name(normalized_name(cells["group"]))
            if group is None:
                plan.new_group = normalize_group_payload({"name": cells["group"]})["name"]
        term_payload["group_id"] = group.id if group else None
    item.plan = plan
    new_group_note = f" Tạo nhóm mới «{plan.new_group}»." if plan.new_group else ""
    if term is None or revision is None:
        item.action, item.message = "create", "Tạo thuật ngữ mới, chờ duyệt." + new_group_note
        return
    stored_link_keys = {(link.kind, link.dataset_id, link.column_name, link.metric_id) for link in stored_links}
    link_keys = {(link["kind"], link["dataset_id"], link["column_name"], link["metric_id"]) for link in links}
    group_given = "group_id" in term_payload
    changes = [
        field
        for field, changed in (
            ("definition", values["definition"] != revision.definition),
            ("synonyms", values["synonyms"] != stored_synonyms),
            ("steward", values["steward_id"] != term.steward_id),
            ("links", link_keys != stored_link_keys),
            ("group", group_given and (plan.new_group is not None or term_payload["group_id"] != term.group_id)),
        )
        if changed
    ]
    plan.term_id, plan.revision_number = term.id, revision.revision_number
    plan.content_changed = any(field != "group" for field in changes)
    if plan.content_changed and unapproved_metrics:
        # A new revision is checked as the editor checks it, which accepts only approved metrics.
        raise GlossaryValidationError("A glossary term may link only approved metrics.")
    item.changes = changes
    if not changes:
        item.action = "unchanged"
    elif not plan.content_changed:
        item.action, item.message = "update", "Chỉ chuyển nhóm; trạng thái duyệt giữ nguyên." + new_group_note
    elif revisions.read_serving(term.id) is not None:
        item.action = "update"
        item.message = "Tạo bản nháp mới chờ duyệt; bản đã duyệt vẫn được dùng tới khi bản nháp được duyệt."
        item.message += new_group_note
    else:
        item.action, item.message = "update", "Tạo bản nháp mới chờ duyệt." + new_group_note


def _steward_id(username: str) -> int | None:
    if not username:
        return None
    user = security_manager.find_user(username=username)
    if user is None:
        raise GlossaryValidationError(f"Không có người dùng «{username}».")
    return user.id


def _link(token: str, datasets: dict[str, list[Any]]) -> dict[str, Any]:
    """Liên kết như trình soạn gửi, từ `dataset:<bảng>`, `column:<bảng>.<cột>` hoặc `metric:<bảng>.<metric>`.

    The table is the dataset's name in Superset; it is split from the column or metric at the last dot.
    """
    kind, _, target = token.partition(":")
    kind, target = kind.strip().casefold(), target.strip()
    table, _, name = target.rpartition(".")
    if kind not in ("dataset", "column", "metric") or not target or (kind != "dataset" and not (table and name)):
        raise GlossaryValidationError(f"Liên kết «{token}» phải có dạng {LINK_FORMAT}.")
    if kind == "dataset":
        return {"kind": "dataset", "dataset_id": dataset_named(target, datasets, GlossaryValidationError).id}
    dataset = dataset_named(table, datasets, GlossaryValidationError)
    if kind == "column":
        column = next((column for column in dataset.columns if column.column_name == name), None)
        if column is None or column.is_active is not True or column.expression:
            raise GlossaryValidationError(f"Dataset «{table}» không có cột vật lý «{name}».")
        return {"kind": "column", "dataset_id": dataset.id, "column_name": name}
    metric = next((metric for metric in dataset.metrics if metric.metric_name == name), None)
    if metric is None:
        raise GlossaryValidationError(f"Dataset «{table}» không có metric «{name}».")
    return {"kind": "metric", "dataset_id": dataset.id, "metric_id": metric.id}


def _link_token(link: Any) -> str:
    dataset = get_dataset(link.dataset_id)
    table = dataset.table_name if dataset else f"#{link.dataset_id}"
    if link.kind == "dataset":
        return f"dataset:{table}"
    if link.kind == "column":
        return f"column:{table}.{link.column_name}"
    metric = next((metric for metric in getattr(dataset, "metrics", []) if metric.id == link.metric_id), None)
    return f"metric:{table}.{metric.metric_name if metric else f'#{link.metric_id}'}"
