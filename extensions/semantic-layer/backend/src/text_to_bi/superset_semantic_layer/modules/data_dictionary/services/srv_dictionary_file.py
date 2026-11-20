from dataclasses import dataclass
from typing import Any

from text_to_bi.superset_semantic_layer.common.exceptions import SemanticLayerError
from text_to_bi.superset_semantic_layer.common.utils.table_file import (
    ImportRow,
    TemplateColumn,
    dataset_named,
    flag_text,
    join_list,
    parse_flag,
    read_table,
    refusal_message,
    split_list,
    write_table,
    write_template,
)
from text_to_bi.superset_semantic_layer.common.utils.type_formatter import json_list
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import business_datasets_by_name

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository
from ..exceptions import DataDictionaryValidationError
from .srv_column_semantics import AGGREGATIONS, ROLES
from .srv_dictionary import validate_dictionary_payload
from .srv_pii import checked_pii_flag
from .srv_seeding import read_dictionary_snapshot, seed_dictionary

# A row with an empty `column` describes the dataset itself, which has only these of the fields.
DATASET_ROW_FIELDS = ("display_name", "description", "contains_pii")
LIST_FIELDS = ("aggregations", "synonyms")
DICTIONARY_FILE_NAME = "data-dictionary"
DICTIONARY_COLUMNS = (
    TemplateColumn("dataset", True, "Tên bảng của dataset nghiệp vụ trong Superset.", "tb_gia_tri_quan_sat"),
    TemplateColumn(
        "column", True,
        f"Tên cột của dataset; để trống thì dòng mô tả chính dataset và chỉ dùng {', '.join(DATASET_ROW_FIELDS)}.",
        "gia_tri_so"
    ),
    TemplateColumn("display_name", False, "Tên hiển thị, tối đa 255 ký tự; không để trống.", "Giá trị đo"),
    TemplateColumn("description", False, "Mô tả nghiệp vụ.", "Giá trị số của chỉ số tại thời điểm quan sát."),
    TemplateColumn(
        "semantic_role", False, f"Một trong: {', '.join(ROLES)}; trống thì giữ vai trò hiện tại.", "measure"
    ),
    TemplateColumn(
        "aggregations", False, f"Chỉ cho cột measure; cách nhau bằng ;: {', '.join(AGGREGATIONS)}.", "AVG; MIN; MAX"
    ),
    TemplateColumn("synonyms", False, "Từ đồng nghĩa, cách nhau bằng ;", "giá trị; số đo"),
    TemplateColumn("unit", False, "Đơn vị đo.", "°C"),
    TemplateColumn("business_term", False, "Thuật ngữ nghiệp vụ của cột.", "Nhiệt độ"),
    TemplateColumn("contains_pii", False, "true hoặc false (cũng nhận 1/0, x, có/không); trống là false.", "false"),
)
# A dataset row then a column row, so the template shows both kinds.
DICTIONARY_EXAMPLE_ROWS = (
    [
        "tb_gia_tri_quan_sat", "", "Giá trị quan sát", "Mỗi dòng là giá trị một chỉ số thời tiết của một lần quan sát.",
        "", "", "", "", "", "false"
    ],
    [column.example for column in DICTIONARY_COLUMNS],
)


@dataclass
class DictionaryPlan:
    record: Any
    values: dict[str, Any]
    is_column: bool


def export_dictionary_template() -> dict[str, str]:
    return write_template(
        DICTIONARY_COLUMNS, DICTIONARY_EXAMPLE_ROWS, DICTIONARY_FILE_NAME, DataDictionaryValidationError
    )


def export_dictionary() -> dict[str, str]:
    rows = []
    for datasets in business_datasets_by_name().values():
        for dataset in datasets:
            record, snapshot_columns = read_dictionary_snapshot(dataset)
            columns = {row.column_name: row for row in snapshot_columns}
            pii = flag_text(record.contains_pii)
            rows.append([dataset.table_name, "", record.display_name, record.description or "", *[""] * 5, pii])
            for actual in dataset.columns:
                row = columns.get(str(actual.column_name))
                if row is None:
                    continue
                rows.append(
                    [
                        dataset.table_name,
                        row.column_name,
                        row.display_name,
                        row.description or "",
                        row.semantic_role or "",
                        join_list(json_list(row.aggregations)),
                        join_list(json_list(row.synonyms)),
                        row.unit or "",
                        row.business_term or "",
                        flag_text(row.contains_pii),
                    ]
                )
    return write_table(DICTIONARY_COLUMNS, rows, DICTIONARY_FILE_NAME, DataDictionaryValidationError)


def preview_dictionary_import(payload: Any) -> list[ImportRow]:
    datasets = business_datasets_by_name()
    first_rows: dict[tuple[int, str], int] = {}
    result = []
    rows = read_table(payload, DICTIONARY_COLUMNS, DataDictionaryValidationError)
    for number, cells in rows:
        key = f"{cells['dataset']}.{cells['column']}" if cells["column"] else cells["dataset"]
        item = ImportRow(row=number, key=key)
        try:
            dataset = dataset_named(cells["dataset"], datasets, DataDictionaryValidationError)
            row_key = (dataset.id, cells["column"])
            if row_key in first_rows:
                raise DataDictionaryValidationError(f"Trùng với dòng {first_rows[row_key]}.")
            first_rows[row_key] = number
            if cells["column"]:
                _plan_column(item, cells, dataset)
            else:
                _plan_dataset(item, cells, dataset)
        except SemanticLayerError as error:
            item.action, item.message, item.changes, item.plan = "error", str(error), [], None
        result.append(item)
    return result


def apply_dictionary_import(payload: Any) -> list[ImportRow]:
    rows = preview_dictionary_import(payload)
    refusal = refusal_message(rows)
    if refusal:
        raise DataDictionaryValidationError(refusal)
    dataset_ids = {
        item.plan.record.dataset_id if item.plan.is_column else item.plan.record.id
        for item in rows if item.plan is not None
    }
    for datasets in business_datasets_by_name().values():
        for dataset in datasets:
            if dataset.id in dataset_ids:
                seed_dictionary(dataset)
    column_repository, dataset_repository = column_dictionary_repository(), dataset_dictionary_repository()
    for item in rows:
        if item.action != "update":
            continue
        plan = item.plan
        plan.record = (
            column_repository.read_by_column_name(plan.record.dataset_id, plan.record.column_name) if plan.is_column
            else dataset_repository.read(plan.record.id)
        )
        if not plan.is_column:
            dataset_repository.update(plan.record, plan.values)
            continue
        row = column_repository.update(plan.record, plan.values)
        # As the editor's save does: only a measure keeps its aggregations.
        if row.semantic_role != "measure" and row.aggregations:
            row.aggregations = None
    return rows


def _plan_dataset(item: ImportRow, cells: dict[str, str], dataset: Any) -> None:
    extra = [name for name, value in cells.items() if value and name not in ("dataset", "column", *DATASET_ROW_FIELDS)]
    if extra:
        raise DataDictionaryValidationError(
            f"Dòng của dataset (cột «column» trống) chỉ có {', '.join(DATASET_ROW_FIELDS)}; "
            f"bỏ trống: {', '.join(extra)}."
        )
    values: dict[str, Any] = {}
    if "display_name" in cells:
        values["display_name"] = _display_name(cells["display_name"])
    if "description" in cells:
        values["description"] = cells["description"] or None
    if "contains_pii" in cells:
        values["contains_pii"] = _pii_flag(cells["contains_pii"])
    _decide(item, DictionaryPlan(read_dictionary_snapshot(dataset)[0], values, is_column=False))


def _plan_column(item: ImportRow, cells: dict[str, str], dataset: Any) -> None:
    column_names = {str(column.column_name) for column in dataset.columns}
    column_name = cells["column"]
    if column_name not in column_names:
        raise DataDictionaryValidationError(f"Dataset «{dataset.table_name}» không có cột «{column_name}».")
    row = next(row for row in read_dictionary_snapshot(dataset)[1] if row.column_name == column_name)
    update: dict[str, Any] = {"column_name": column_name}
    if "display_name" in cells:
        update["display_name"] = _display_name(cells["display_name"])
    # A blank role keeps the stored one: every column has a role, and the editor offers no way to clear it.
    if cells.get("semantic_role"):
        if cells["semantic_role"] not in ROLES:
            raise DataDictionaryValidationError(
                f"Vai trò «{cells['semantic_role']}» không hợp lệ; dùng một trong: {', '.join(ROLES)}."
            )
        update["semantic_role"] = cells["semantic_role"]
    if "aggregations" in cells:
        aggregations = [value.upper() for value in split_list(cells["aggregations"])]
        unknown = [value for value in aggregations if value not in AGGREGATIONS]
        if unknown:
            raise DataDictionaryValidationError(
                f"Phép tổng hợp không hợp lệ: {', '.join(unknown)}; dùng: {', '.join(AGGREGATIONS)}."
            )
        if aggregations and update.get("semantic_role", row.semantic_role) != "measure":
            raise DataDictionaryValidationError("Chỉ khai báo phép tổng hợp cho cột có vai trò measure.")
        update["aggregations"] = aggregations
    for field in ("description", "unit", "business_term"):
        if field in cells:
            update[field] = cells[field] or None
    if "synonyms" in cells:
        update["synonyms"] = split_list(cells["synonyms"])
    if "contains_pii" in cells:
        update["contains_pii"] = _pii_flag(cells["contains_pii"])
    try:
        values = validate_dictionary_payload({"columns": [update]}, column_names, dataset.id)[0]
    except DataDictionaryValidationError as error:
        raise DataDictionaryValidationError(str(error).replace("columns[0].", "")) from error
    values.pop("column_name")
    _decide(item, DictionaryPlan(row, values, is_column=True))


def _decide(item: ImportRow, plan: DictionaryPlan) -> None:
    item.plan = plan
    item.changes = [
        field
        for field, value in plan.values.items()
        if _comparable(field, getattr(plan.record, field)) != _comparable(field, value)
    ]
    item.action = "update" if item.changes else "unchanged"


def _comparable(field: str, value: Any) -> Any:
    if field in LIST_FIELDS:
        return json_list(value)
    if field == "contains_pii":
        return bool(value)
    return value


def _display_name(text: str) -> str:
    if not text:
        raise DataDictionaryValidationError("Tên hiển thị (display_name) không được để trống.")
    if len(text) > 255:
        raise DataDictionaryValidationError("Tên hiển thị (display_name) dài quá 255 ký tự.")
    return text


def _pii_flag(text: str) -> bool:
    flag = parse_flag(text)
    if flag is None:
        raise DataDictionaryValidationError(f"contains_pii «{text}» phải là true hoặc false.")
    return checked_pii_flag(flag, "contains_pii")
