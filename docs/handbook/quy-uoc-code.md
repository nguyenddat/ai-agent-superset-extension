# Quy ước code

Áp dụng cho Python và TypeScript trong toàn repository. Phần lớn code của `extensions/text-to-bi` được chuyển từ
repository standalone và giữ quy ước của nó; chỗ khác do chạy trong Superset 6.1 (Python 3.10, SQLAlchemy 1.4, Flask,
React 17) được ghi rõ.

## Độ dài dòng và xuống dòng

- Python: một dòng tối đa 120 ký tự. Ruff kiểm tra với giới hạn này (`line-length = 120`, `extend-select = ["E501",
  "I"]` trong `pyproject.toml` ở gốc và ở `extensions/text-to-bi/backend/`). Prompt gửi mô hình giữ nguyên chữ nên
  `agent_package/prompts/*.py` được miễn `E501`.
- Chỉ xuống dòng khi vượt 120 ký tự. Lời gọi hàm, import, dict hay comprehension vừa một dòng thì để trên một dòng.
- Khi phải xuống dòng, ngắt gọn bên trong cặp ngoặc ngoài cùng và dồn mỗi dòng gần đủ 120 ký tự; không bung mỗi tham
  số một dòng nếu không cần. Không chạy `ruff format` hay Prettier trên code có sẵn.
- Frontend không có formatter hay linter. Code chuyển từ standalone giữ định dạng gốc, kể cả dòng dài hơn 120 ký tự
  (thường là chuỗi `className`); code mới tự giữ 120 ký tự khi được.

```python
# Đúng
datasets = {dataset.id: dataset for dataset in get_datasets(dataset_ids)}

# Đúng: vượt 120 ký tự, ngắt gọn
result = service.chat(
    database_id, body.question, body.chat_history, current_user_id(), body.conversation_id, body.resume_id,
)

# Sai: vừa một dòng mà vẫn tách
datasets = {
    dataset.id: dataset
    for dataset in get_datasets(dataset_ids)
}
```

## Đặt tên

- Đặt tên theo nghĩa nghiệp vụ: `metric_contract`, `selected_dataset`, `approved_at`, `metricContract`.
- Không viết tắt (`ds`, `col`, `m`, `tmp`, `res`). Tên một chữ cái chỉ dùng cho chỉ số vòng lặp ngắn.
- Hàm trả đối tượng hoặc `None` đặt `get_…`; hàm ném lỗi khi không thấy hoặc thiếu quyền đặt `require_…`
  (`require_dataset`, `require_admin`, `require_query`); hàm trả `bool` về quyền đặt `can_…` / `is_…`.
- Exception kết thúc bằng `Error` và có `code` dạng `snake_case` ổn định: `MetricConflictError`,
  `QueryRequiredError` (`query_permission_required`). Lỗi của `text2sql` giữ tên từ standalone
  (`Text2SqlInvalidRequest`).
- Tên file trong module giữ theo nguồn standalone (`route_*.py`, `srv_*.py`, `repo_*.py`, hoặc `metric_service.py`,
  `metric_repository.py`); file mới đặt theo file cùng thư mục.
- Có type hint cho tham số, giá trị trả về và thuộc tính quan trọng.

## Import

- Trong cùng một module (`modules/<module>/`) import tương đối: `from ..migrations import ensure_metric_tables`.
- Ra ngoài module, kể cả sang `common`, `core`, `agent_package` hay module khác, import tuyệt đối từ tên package đầy
  đủ: `from text_to_bi.superset_text_to_bi.common.base_exceptions import AppError`. Không viết `from common...`:
  Superset nạp `.supx` theo tên module đầy đủ nên không có package `common` ở cấp cao nhất.
- Nhóm import tương đối đặt sau nhóm import tuyệt đối. Ruff kiểm tra thứ tự (`I`); sắp lại bằng
  `uv run ruff check --select I --fix <file>`.
- Frontend import qua alias `@/` (`@/lib/api`, `@/components/ui/button`); trong cùng một thư mục `features/<module>/`
  import tương đối (`./types`).

## Docstring và comment

- Không thêm docstring cho module, class và hàm. Tên hàm, tên tham số và type hint phải đủ nói hàm làm gì; điều tên
  không nói được (khi nào trả `None`, ném lỗi gì, vì sao làm vậy) ghi bằng comment ngắn ngay trên hàm. Vài file chuyển
  sang còn docstring (một số `migrations.py`, `chat_stream.with_request_user`); không lấy đó làm mẫu.
- Ngoại lệ: script trong `scripts/` giữ module docstring vì `argparse` dùng `__doc__` làm nội dung `--help`.
- Comment giải thích *vì sao*, không thuật lại code.

## Code dùng chung

- Dùng lại hàm sẵn có thay vì viết lại: thời gian dùng `common/utils/type_formatters.py` (`utc_now`, `iso_datetime`,
  `iso_date`, `parse_datetime`); response của module quản trị dùng `json_payload` (`modules/management_payload.py`);
  thân request dùng `request_body(Schema)` và tham số số nguyên dùng `query_int` (`core/validation.py`).
- Truy vấn dataset, database, người dùng, nhóm quyền của Superset đi qua `modules/superset/services/`; kiểm tra quyền
  đi qua `modules/auth/services/srv_access.py`.
- Không kiểm tra lại điều hàm được gọi đã xử lý; ví dụ `get_datasets([])` đã trả `[]`.

## Dữ liệu và định dạng

- Bảng mới kế thừa `BaseModel` (hoặc `AuditedModel` khi cần biết ai tạo, ai sửa) của `common/base_model.py`: nằm trong
  schema `text_to_bi`, khóa chính UUID v7, `created_at` / `updated_at` có timezone. Cột Superset tham chiếu bằng FK
  tới model chuẩn của Superset.
- Dùng `datetime` có timezone và chuẩn hóa UTC trước khi lưu; cột thời gian dùng `DateTime(timezone=True)`.
- Không suy đoán timezone của datetime không có timezone. Không chuyển `Decimal` sang `float` khi độ chính xác có ý
  nghĩa.
- Thân request và response khai báo bằng Pydantic trong `schemas/` của module.

## Biến môi trường và bí mật

- Backend đọc biến môi trường qua `settings` của `core/config.py`; không gọi `os.getenv` trong module. Thêm biến mới
  thì khai báo trong `Settings` và ghi vào `.env.example`.
- Không đưa khóa API hay mật khẩu vào commit, bundle, log hay tài liệu. Giá trị thật chỉ nằm trong `.env` ở gốc
  repository; Compose nạp file này vào các container Superset.

## Frontend

- React 17: không dùng API của React 18+; `useSyncExternalStore` và `useId` lấy từ `@/lib/react-compat`. Không thêm
  bản React riêng: `react` / `react-dom` là singleton chia sẻ với Superset qua Module Federation.
- Component UI thêm bằng shadcn (`components.json`, style `base-nova`, Base UI, icon `lucide-react`) vào
  `src/components/ui/`.
- Tailwind v4 không có preflight: class chỉ có hiệu lực bên trong `.tb-page`, popup phải portal vào gốc đó
  (`usePortalContainer`). CSS ngoài `.tb-page` chỉ dành cho menu navbar (`.tb-nav-*` trong `styles/globals.css`);
  không viết CSS chạm vào phần tử của Superset.
- Gọi API bằng `apiFetch` của `@/lib/api` (tự gắn cookie phiên và `X-CSRFToken`); đọc dữ liệu bằng hook SWR trong
  `features/<module>/api.ts`. Quyền hiển thị lấy từ `Access` (`/auth/me`), nhưng backend vẫn là nơi quyết định.
- Văn bản giao diện bằng tiếng Việt có dấu.
- Kiểm tra bằng `npm run typecheck` trong `extensions/text-to-bi/frontend` (hoặc `uv run scripts/check.py`).

## Test

- Chạy từ gốc repository: `uv run ruff check`, `uv run pytest extensions/text-to-bi/backend/tests`,
  `uv run pytest scripts/tests`; hoặc tất cả cùng typecheck frontend bằng `uv run scripts/check.py`.
- Test backend chạy trên Python 3.12 với `superset` giả lập trong `tests/conftest.py`, nên không bắt được lỗi API
  Superset hay cú pháp Python 3.10; chạy thêm `uv run scripts/compat.py` và `uv run scripts/smoke.py` khi stack đang
  chạy.
- **Hiện trạng:** chỉ `test_common.py` chạy được. `test_data_dictionary_api.py`, `test_data_dictionary_autofill.py`
  và `test_migrations.py` lỗi ngay khi nạp, `test_auth.py` lỗi khi dựng fixture, vì `conftest.py` chưa giả lập
  `superset.connectors` và `superset.models.core`. Vì vậy `scripts/check.py` đang báo lỗi ở bước pytest.
- Sửa một lỗi hành vi thì thêm test tái hiện lỗi đó.

## Tài liệu

- Tài liệu trong `docs/` viết tiếng Việt có dấu, mã hóa UTF-8 (riêng `docs/release.md` viết tiếng Anh). Dùng link
  tương đối cho file trong repository.
- Tài liệu một tính năng ghi trạng thái **đã triển khai** hoặc **dự kiến**, và phân biệt hành vi hiện có với quyết định
  thiết kế.

## Commit message

Dùng [Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>): <description>`.

- `type`: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `build`, `perf`, `style`, `ci`.
- `scope`: phần bị sửa, ví dụ `text-to-bi`, `text2sql`, `scripts`, `simulation`, `handbook`, `docs`.
- `description`: tiếng Anh, thể mệnh lệnh, chữ thường ở đầu, không có dấu chấm cuối.
- Thân commit (nếu có) giải thích vì sao và những gì thay đổi về hành vi; thay đổi phá vỡ tương thích ghi
  `BREAKING CHANGE:` ở chân.

```text
feat(text-to-bi): add conversation module
fix(text-to-bi): audit module integration and validation
docs(handbook): record the module layout and error handling
```
