import base64
import binascii
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

MAX_FILE_BYTES = 1_000_000
MAX_ROWS = 1_000
# Blank lines are skipped, so a few more are read before a file counts as too long.
MAX_LINES = MAX_ROWS * 5
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DATA_SHEET = "Dữ liệu"
GUIDE_SHEET = "Hướng dẫn"
GUIDE_HEADERS = ("Cột", "Bắt buộc", "Giá trị / định dạng", "Ví dụ")
HEADER_FILL = "D9E2F3"
MAX_COLUMN_WIDTH = 60
LIST_SEPARATOR = ";"
_TRUE_WORDS = {"true", "1", "x", "yes", "có", "đúng"}
_FALSE_WORDS = {"false", "0", "", "no", "không", "sai"}


@dataclass(frozen=True)
class TemplateColumn:
    """Một cột của file Excel: tên tiêu đề, có bắt buộc không, giá trị hoặc định dạng cho phép và ví dụ."""

    name: str
    required: bool
    description: str
    example: str = ""


@dataclass
class ImportRow:
    """What importing one row of a file does: `create`, `update`, `unchanged` or `error`, with a Vietnamese note.

    `row` is the spreadsheet row number (the header is row 1). `plan` holds what the module needs to apply the row
    and is never sent to the client.
    """

    row: int
    key: str
    action: str = "error"
    message: str | None = None
    changes: list[str] = field(default_factory=list)
    plan: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "row": self.row, "key": self.key, "action": self.action, "message": self.message, "changes": self.changes,
        }


def import_report(rows: list[ImportRow]) -> dict[str, Any]:
    """The preview or result of an import: every row, and how many rows of each action."""
    summary = {action: 0 for action in ("create", "update", "unchanged", "error")}
    for item in rows:
        summary[item.action] += 1
    return {"rows": [item.as_dict() for item in rows], "summary": summary}


def refusal_message(rows: list[ImportRow]) -> str | None:
    """Why an import saves nothing: some rows fail. None when every row can be applied."""
    failed = sum(item.action == "error" for item in rows)
    if not failed:
        return None
    return f"File có {failed} dòng lỗi; sửa các dòng đó rồi tải lên lại. Chưa có thay đổi nào được lưu."


def dataset_named(name: str, datasets: dict[str, list[Any]], error: type[Exception]) -> Any:
    """The one dataset with this table name among `datasets` (table name → datasets), as a file names a dataset."""
    matches = datasets.get(name, [])
    if not matches:
        raise error(f"Không có dataset «{name}».")
    if len(matches) > 1:
        raise error(f"Có {len(matches)} dataset cùng tên «{name}»; đổi tên một dataset trong Superset để phân biệt.")
    return matches[0]


def split_list(cell: str) -> list[str]:
    """The items of a cell that lists several values separated by `;`, trimmed, blanks dropped."""
    return [part.strip() for part in cell.split(LIST_SEPARATOR) if part.strip()]


def join_list(values: Iterable[str]) -> str:
    return f"{LIST_SEPARATOR} ".join(values)


def parse_flag(cell: str) -> bool | None:
    """A yes/no cell (`true`/`false`, `1`/`0`, `x`, `có`/`không`); None when it is neither. Blank reads as no."""
    word = cell.strip().casefold()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    return None


def flag_text(value: Any) -> str:
    return "true" if value else "false"


def read_table(payload: Any, columns: Sequence[TemplateColumn], error: type[Exception]) -> list[tuple[int, dict[str, str]]]:
    """Các dòng dữ liệu của file Excel tải lên, mỗi dòng kèm số dòng trong bảng tính và ô theo tên cột.

    `payload` là thân request `{"filename": ..., "content": <base64>}`. Đọc sheet "Dữ liệu", không có thì sheet đầu.
    Tên cột so khớp không phân biệt hoa thường và khoảng trắng; thiếu hẳn một cột không bắt buộc thì giữ nguyên trường
    đó. Ném `error` với thông điệp tiếng Việt khi file quá lớn, không phải Excel, trống, hoặc sai cột.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), str) or not payload["content"]:
        raise error("Chọn một file Excel (.xlsx) để tải lên.")
    too_large = f"File vượt quá {MAX_FILE_BYTES // 1_000_000} MB."
    if len(payload["content"]) > (MAX_FILE_BYTES + 2) // 3 * 4:
        raise error(too_large)
    try:
        data = base64.b64decode(payload["content"], validate=True)
    except (binascii.Error, ValueError) as ex:
        raise error("Không đọc được nội dung file.") from ex
    if len(data) > MAX_FILE_BYTES:
        raise error(too_large)
    # An XLSX file is a zip archive, which starts with "PK".
    if data[:2] != b"PK":
        raise error("Chỉ nhận file Excel (.xlsx); tải file mẫu rồi điền dữ liệu vào đó.")
    lines = _xlsx_lines(data, error)
    if not lines:
        raise error("File trống.")
    too_long = f"File có hơn {MAX_ROWS} dòng; chia nhỏ file rồi tải lên lần lượt."
    if len(lines) > MAX_LINES:
        raise error(too_long)
    headers = [column.name for column in columns]
    known = {_header_key(name): name for name in headers}
    present_columns: list[str | None] = []
    unknown = []
    for cell in lines[0]:
        key = _header_key(cell)
        if key and key not in known:
            unknown.append(cell.strip())
        present_columns.append(known.get(key))
    if unknown:
        raise error(f"File có cột không hỗ trợ: {', '.join(unknown)}. Các cột được nhận: {', '.join(headers)}.")
    present = [name for name in present_columns if name is not None]
    if len(present) != len(set(present)):
        raise error("File có cột bị lặp tên.")
    missing = [column.name for column in columns if column.required and column.name not in present]
    if missing:
        raise error(f"File thiếu cột: {', '.join(missing)}.")
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        cells = {name: (line[index].strip() if index < len(line) else "") for index, name in enumerate(present_columns) if name}
        if any(cells.values()):
            rows.append((number, cells))
    if not rows:
        raise error("File không có dòng dữ liệu nào.")
    if len(rows) > MAX_ROWS:
        raise error(too_long)
    return rows


def write_table(columns: Sequence[TemplateColumn], rows: Iterable[Sequence[str]], name: str, error: type[Exception]) -> dict[str, str]:
    """File Excel theo mẫu chung: sheet "Dữ liệu" chứa `rows`, sheet "Hướng dẫn" mô tả từng cột.

    Trả `{"filename", "media_type", "content": <base64>}`; import đọc lại được đúng file này.
    """
    content = base64.b64encode(_xlsx_bytes(columns, rows, error)).decode("ascii")
    return {"filename": f"{name}.xlsx", "media_type": XLSX_MEDIA_TYPE, "content": content}


def write_template(columns: Sequence[TemplateColumn], example_rows: Iterable[Sequence[str]], name: str, error: type[Exception]) -> dict[str, str]:
    """File mẫu để điền: cùng bố cục với file xuất, chứa vài dòng ví dụ."""
    return write_table(columns, example_rows, f"{name}-mau", error)


def _header_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return flag_text(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _xlsx_lines(data: bytes, error: type[Exception]) -> list[list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as ex:
        raise error("Máy chủ chưa đọc được file Excel.") from ex
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = workbook[DATA_SHEET] if DATA_SHEET in workbook.sheetnames else workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        lines = [[_cell_text(value) for value in row] for _, row in zip(range(MAX_LINES + 1), rows)]
        workbook.close()
    except Exception as ex:
        raise error("Không đọc được file Excel.") from ex
    return lines


def _xlsx_bytes(columns: Sequence[TemplateColumn], rows: Iterable[Sequence[str]], error: type[Exception]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as ex:
        raise error("Máy chủ chưa tạo được file Excel.") from ex
    workbook = Workbook()
    data_sheet = workbook.active
    data_sheet.title = DATA_SHEET
    _fill_sheet(data_sheet, [column.name for column in columns], rows)
    guide_rows = [[column.name, "Có" if column.required else "Không", column.description, column.example] for column in columns]
    _fill_sheet(workbook.create_sheet(GUIDE_SHEET), GUIDE_HEADERS, guide_rows)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _fill_sheet(sheet: Any, headers: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Ghi tiêu đề in đậm có nền, cố định dòng tiêu đề, xuống dòng trong ô và đặt độ rộng cột theo nội dung."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", start_color=HEADER_FILL, end_color=HEADER_FILL)
    # Multi-line cells (conditions, examples) stay readable instead of running on one line.
    for line in sheet.iter_rows(min_row=2):
        for cell in line:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    for index, column_cells in enumerate(sheet.iter_cols(), start=1):
        longest = max((len(line) for cell in column_cells for line in str(cell.value or "").split("\n")), default=0)
        sheet.column_dimensions[get_column_letter(index)].width = min(MAX_COLUMN_WIDTH, max(12, longest + 2))
