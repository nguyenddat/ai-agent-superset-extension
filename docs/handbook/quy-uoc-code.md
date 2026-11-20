# Quy ước code

Áp dụng cho Python và TypeScript trong toàn repository. Quy ước này thống nhất với repository standalone; chỗ khác do
chạy trong Superset 6.1 (Python 3.10, SQLAlchemy 1.4, Flask) được ghi rõ.

## Độ dài dòng và xuống dòng

- Một dòng tối đa 120 ký tự. Ruff kiểm tra Python với giới hạn này (`E501` trong `pyproject.toml` ở gốc và ở mỗi
  `extensions/*/backend/`); frontend không có formatter nên tự giữ giới hạn, cả TypeScript lẫn CSS.
- Chỉ xuống dòng khi vượt 120 ký tự. Lời gọi hàm, import, object, comprehension hay JSX element vừa một dòng thì để trên
  một dòng.
- Khi phải xuống dòng, ngắt gọn bên trong cặp ngoặc ngoài cùng và dồn mỗi dòng tiếp theo gần đủ 120 ký tự; không bung mỗi
  tham số một dòng nếu không cần. Không chạy `ruff format` hay Prettier trên code có sẵn.
- Prompt gửi mô hình ngôn ngữ giữ nguyên chữ: chuỗi trong triple quote không ngắt dòng; file prompt được miễn `E501`
  trong `per-file-ignores`.

```python
# Đúng
datasets = {dataset.id: dataset for dataset in get_datasets(dataset_ids)}

# Đúng: vượt 120 ký tự, ngắt gọn
return TurnOutcome(
    self.status, masker.unmask(self.answer),
    masker.unmask(self.clarification_question) if self.clarification_question else None,
)

# Sai: vừa một dòng mà vẫn tách
datasets = {
    dataset.id: dataset
    for dataset in get_datasets(dataset_ids)
}
```

## Đặt tên

- Đặt tên theo nghĩa nghiệp vụ: `metric_contract`, `selected_dataset`, `approved_at`, `metricContract`.
- Không viết tắt (`ds`, `col`, `m`, `tmp`, `res`, `refs`). Tên một chữ cái chỉ dùng cho chỉ số vòng lặp ngắn.
- Hàm trả về đối tượng hoặc `None` đặt `get_…` / `…_for`; hàm ném lỗi khi không thấy đặt `require_…`
  (`require_dataset`, `require_admin`).
- Exception đặt tên theo điều đã xảy ra và kết thúc bằng `Error`: `MetricContractNotFoundError`,
  `GlossarySelfApprovalError`.
- Có type hint cho tham số, giá trị trả về và thuộc tính quan trọng.

## Import

- Trong cùng một module (`modules/<module>/`) import tương đối: `from ..models.model_metric import MetricContract`.
- Ra ngoài module, kể cả sang `common`, `core` hay module khác, import tuyệt đối từ tên package đầy đủ:
  `from text_to_bi.superset_semantic_layer.common.base_repo import BaseRepository`. Không viết `from common...`:
  Superset nạp `.supx` theo tên module đầy đủ nên không có package `common` ở cấp cao nhất.
- Nhóm import tương đối đặt sau nhóm import tuyệt đối. Ruff kiểm tra thứ tự (`I`); sắp lại bằng
  `uv run ruff check --select I --fix <file>`.

## Docstring và comment

- Không viết docstring cho module, class và hàm. Tên hàm, tên tham số và type hint phải đủ nói hàm làm gì; điều tên
  không nói được (khi nào trả `None`, ném lỗi gì, vì sao làm vậy) ghi bằng comment ngắn.
- Ngoại lệ: script trong `scripts/` giữ module docstring vì `argparse` dùng `__doc__` làm nội dung `--help`.
- Comment giải thích *vì sao*, không thuật lại code.

## Code dùng chung

- Dùng lại hàm sẵn có thay vì viết lại: định dạng thời gian và JSON dùng `common/utils/type_formatter.py`
  (`iso_datetime`, `iso_date`, `compact_json`, …), không tự gọi `.isoformat()`.
- Không kiểm tra lại điều hàm được gọi đã xử lý; ví dụ `get_datasets([])` đã trả `[]`, nên không bọc thêm
  `if dataset_ids else`.

## Dữ liệu và định dạng

- Dùng `datetime` có timezone và chuẩn hóa UTC trước khi lưu. Cột thời gian dùng `DateTime(timezone=True)`.
- Không suy đoán timezone của datetime không có timezone. Không chuyển `Decimal` sang `float` khi độ chính xác có ý nghĩa.

## Biến môi trường và bí mật

- Mỗi extension đọc biến môi trường dùng chung qua lớp `Settings` trong `core/config.py`; không gọi `os.getenv` trong
  module.
- Không đưa khóa API hay mật khẩu vào commit, bundle, log hay tài liệu. Giá trị thật chỉ nằm trong `.env` ở gốc
  repository.

## Test

- Chạy từ gốc repository: `uv run pytest extensions/semantic-layer/backend/tests`, `uv run ruff check`.
- Test backend chạy trên Python 3.12 với `superset` giả lập, nên không bắt được lỗi API Superset hay cú pháp Python
  3.10; chạy thêm `uv run scripts/compat.py` và `uv run scripts/smoke.py` khi stack đang chạy.
- Test route biên dịch method thật của route với các đối tượng giả qua `tests/catalog_source.py`. Khi thêm một file
  service mà route gọi trực tiếp, thêm đường dẫn của nó vào `SHARED_SERVICE_PATHS` để test tìm được hàm.
- Sửa một lỗi hành vi thì thêm test tái hiện lỗi đó.

## Tài liệu

- Tài liệu trong `docs/` viết tiếng Việt có dấu, mã hóa UTF-8. Dùng link tương đối cho file trong repository.
- Tài liệu một tính năng ghi trạng thái **đã triển khai** hoặc **dự kiến**, và phân biệt hành vi hiện có với quyết định
  thiết kế.

## Commit message

Dùng [Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>): <description>`.

- `type`: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `build`, `perf`, `style`, `ci`.
- `scope`: phần bị sửa, ví dụ `semantic-layer`, `ai-agent`, `simulation`, `scripts`, `docs`.
- `description`: tiếng Anh, thể mệnh lệnh, chữ thường ở đầu, không có dấu chấm cuối.
- Thân commit (nếu có) giải thích vì sao và những gì thay đổi về hành vi; thay đổi phá vỡ tương thích ghi
  `BREAKING CHANGE:` ở chân.

```text
fix(semantic-layer): answer an expert rule name collision with 400
refactor(semantic-layer): move Superset lookups into the superset module
docs(handbook): record the module layout and error handling
```
