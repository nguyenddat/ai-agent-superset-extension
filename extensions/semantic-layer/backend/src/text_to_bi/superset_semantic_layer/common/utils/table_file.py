import base64
import binascii
import csv
import io
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

MAX_FILE_BYTES = 1_000_000
MAX_ROWS = 1_000
# Blank lines are skipped, so a few more are read before a file counts as too long.
MAX_LINES = MAX_ROWS * 5
FILE_FORMATS = {
    "csv": "text/csv;charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
LIST_SEPARATOR = ";"
_TRUE_WORDS = {"true", "1", "x", "yes", "có", "đúng"}
_FALSE_WORDS = {"false", "0", "", "no", "không", "sai"}


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


def read_table(
    payload: Any, headers: Sequence[str], required: Iterable[str], error: type[Exception]
) -> list[tuple[int, dict[str, str]]]:
    """The data rows of an uploaded CSV or XLSX file, each with its spreadsheet row number and its cells by header.

    `payload` is the request body `{"filename": ..., "content": <base64>}`. Headers match without regard to case or
    spacing; a row holds only the headers the file has, so a missing optional header leaves that field as it is.
    Raises `error` with a Vietnamese message for a file that is too large, unreadable, empty, or has unknown or
    missing headers.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), str) or not payload["content"]:
        raise error("Chọn một file CSV hoặc XLSX để tải lên.")
    filename = payload.get("filename") if isinstance(payload.get("filename"), str) else ""
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
    is_xlsx = data[:2] == b"PK" or filename.lower().endswith(".xlsx")
    lines = _xlsx_lines(data, error) if is_xlsx else _csv_lines(data, error)
    if not lines:
        raise error("File trống.")
    too_long = f"File có hơn {MAX_ROWS} dòng; chia nhỏ file rồi tải lên lần lượt."
    if len(lines) > MAX_LINES:
        raise error(too_long)
    known = {_header_key(name): name for name in headers}
    columns: list[str | None] = []
    unknown = []
    for cell in lines[0]:
        key = _header_key(cell)
        if key and key not in known:
            unknown.append(cell.strip())
        columns.append(known.get(key))
    if unknown:
        raise error(f"File có cột không hỗ trợ: {', '.join(unknown)}. Các cột được nhận: {', '.join(headers)}.")
    present = [name for name in columns if name is not None]
    if len(present) != len(set(present)):
        raise error("File có cột bị lặp tên.")
    missing = [name for name in required if name not in present]
    if missing:
        raise error(f"File thiếu cột: {', '.join(missing)}.")
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        cells = {name: (line[index].strip() if index < len(line) else "") for index, name in enumerate(columns) if name}
        if any(cells.values()):
            rows.append((number, cells))
    if not rows:
        raise error("File không có dòng dữ liệu nào.")
    if len(rows) > MAX_ROWS:
        raise error(too_long)
    return rows


def write_table(
    headers: Sequence[str], rows: Iterable[Sequence[str]], file_format: str, name: str, error: type[Exception]
) -> dict[str, str]:
    """A CSV or XLSX file of `rows` under `headers`, as `{"filename", "media_type", "content": <base64>}`.

    The CSV starts with a byte order mark so Excel reads its Vietnamese text as UTF-8.
    """
    if file_format not in FILE_FORMATS:
        raise error("Định dạng file phải là csv hoặc xlsx.")
    if file_format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(headers)
        writer.writerows(rows)
        data = buffer.getvalue().encode("utf-8-sig")
    else:
        data = _xlsx_bytes(headers, rows, name, error)
    content = base64.b64encode(data).decode("ascii")
    return {"filename": f"{name}.{file_format}", "media_type": FILE_FORMATS[file_format], "content": content}


def _header_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _csv_lines(data: bytes, error: type[Exception]) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel's plain "CSV" on a Vietnamese Windows saves in the Windows Vietnamese code page.
        text = data.decode("cp1258", errors="replace")
    # That code page, like macOS, writes tone marks as combining characters; names match in their composed form.
    text = unicodedata.normalize("NFC", text)
    first_line = text.split("\n", 1)[0]
    delimiter = max((",", ";", "\t"), key=first_line.count)
    try:
        return [line for _, line in zip(range(MAX_LINES + 1), csv.reader(io.StringIO(text), delimiter=delimiter))]
    except csv.Error as ex:
        raise error("Không đọc được file CSV.") from ex


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
        raise error("Máy chủ chưa đọc được file XLSX; hãy dùng file CSV.") from ex
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = workbook.worksheets[0].iter_rows(values_only=True)
        lines = [[_cell_text(value) for value in row] for _, row in zip(range(MAX_LINES + 1), rows)]
        workbook.close()
    except Exception as ex:
        raise error("Không đọc được file XLSX.") from ex
    return lines


def _xlsx_bytes(headers: Sequence[str], rows: Iterable[Sequence[str]], name: str, error: type[Exception]) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as ex:
        raise error("Máy chủ chưa tạo được file XLSX; hãy dùng file CSV.") from ex
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = name[:31]
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    # Multi-line cells (conditions, examples) stay readable instead of running on one line.
    for line in sheet.iter_rows(min_row=2):
        for cell in line:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
