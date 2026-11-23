# Hành vi chung của API

Mô tả cách backend `superset-text-to-bi` trả lỗi, giữ transaction và kiểm tra quyền. Mọi route mới theo đúng các quy
tắc này để client nhận cùng một kiểu phản hồi ở mọi nơi.

## Exception và mã lỗi

Lỗi của extension trả HTTP status cùng thân `{"code": "...", "message": "..."}` (`core/routing.error_response`).
`code` là chuỗi ổn định để client so khớp; `message` là văn bản tiếng Việt an toàn để hiện cho người dùng. Lỗi
401/403 do Flask-AppBuilder tự trả (chưa đăng nhập, thiếu permission class) có dạng `{"msg": "..."}`;
`frontend/src/lib/api.ts` đọc cả hai.

`common/base_exceptions.py` giữ các lớp gốc, kế thừa `AppError`. Chúng là lớp trừu tượng (khởi tạo trực tiếp ném
`TypeError`); lớp con trong module là lớp cụ thể và đặt `code`, `message` riêng:

| Lớp gốc | Status | Dùng khi |
| --- | --- | --- |
| `ValidationError` | 422 | Dữ liệu gửi lên phạm quy tắc; cũng là `ValueError` |
| `NotAuthenticatedError` | 401 | Chưa đăng nhập (`SignInRequiredError`) |
| `NotAuthorizedError` | 403 | Thiếu nhóm quyền Text to BI, thiếu quyền dataset, sai CSRF |
| `NotFoundError` | 404 | Bản ghi được nêu không tồn tại hoặc người gọi không được thấy |
| `ConflictError` | 409 | Xung đột trạng thái: trùng tên, duyệt bản không phải nháp |
| `TooManyRequestsError` | 429 | Quá nhiều yêu cầu đang chờ xử lý |
| `BadGatewayError` | 502 | Dịch vụ phụ thuộc trả kết quả không hợp lệ |
| `ServiceUnavailableError` | 503 | Dịch vụ ngoài (OpenRouter, Qdrant) chưa sẵn sàng hoặc thiếu cấu hình |

Quy tắc:

- Mỗi module khai báo lỗi trong `modules/<module>/exceptions.py` (`text2sql`: `utils/exceptions.py`). Lỗi của kiểm tra
  dùng chung nằm trong `core/exceptions.py` (`CsrfTokenError`, `RequestBodyError`, `QueryParameterError`); lỗi quyền
  trong `modules/auth/exceptions.py`; lỗi không thấy dataset, database trong `modules/superset/exceptions.py`.
- Service và route `raise` lỗi của module; không `return self.response(4xx, …)` và không ném `ValueError` /
  `PermissionError` trần ra tới route.
- Thông điệp không chứa SQL, stack trace hay chi tiết nội bộ. `request_body` trả một thông điệp chung
  (`invalid_request`) thay vì chi tiết của Pydantic.
- Lỗi thư viện (ví dụ `IntegrityError`) được bắt ở nơi biết nghĩa nghiệp vụ của nó và đổi thành lỗi của module.

## Thứ tự decorator của route

```python
@expose("/<metric_id>/approve", methods=("POST",))
@protect()
@safe
@permission_name("write")   # GET: "read"; route thay đổi dữ liệu: "write"
@csrf_protected             # chỉ route thay đổi dữ liệu
@rollback_on_error          # chỉ route thay đổi dữ liệu
@handle_errors              # dưới mọi decorator của Superset
@requires_dataset           # nếu có: nạp dataset từ ID trên URL, sát hàm nhất
def approve_metric(self, metric_id: str):
    ...
```

- `@protect()` và `@permission_name` kiểm tra permission class `text_to_bi_api` của Flask-AppBuilder trước khi route
  chạy: `can_read` cho route `read`, `can_write` cho route `write`. Đây chỉ là cửa vào; quyền thật nằm ở kiểm tra
  của module `auth` bên dưới.
- `handle_errors` (`core/database.py`) bắt `AppError`, rollback session và trả `status` cùng `{code, message}`. Nó
  phải nằm dưới `@safe` và `rollback_on_error`, vì hai decorator đó biến mọi exception thành 500.
- `rollback_on_error` bắt lỗi ngoài dự kiến, ghi log, rollback và trả 500 `internal_error` "Đã xảy ra lỗi hệ thống.".
- `csrf_protected` (`core/security.py`) đọc header `X-CSRFToken`; token sai trả 403 `csrf_token_invalid`.
- `@requires_dataset` (`modules/superset/dependencies.py`) lấy `dataset_id` khỏi tham số URL, truyền `dataset` vào
  hàm, ném 404 của module `superset` để `handle_errors` trả về.
- Route chỉ đọc không cần `csrf_protected` và `rollback_on_error` nhưng vẫn có `handle_errors`. Route POST không ghi
  dữ liệu (`/data-lineage/preview`, `/text2sql/retrieve`) khai báo `permission_name("read")`.
- `POST /text2sql/chat/stream` không có `rollback_on_error`: lỗi sau khi stream đã mở được gửi thành sự kiện SSE
  `error` với `{code, message}`, lỗi ngoài dự kiến chỉ hiện "Lỗi không mong muốn khi xử lý câu hỏi.".

## Transaction

- Route sở hữu transaction: gọi `db.session.commit()` một lần khi mọi bước đã xong. Service và repository không
  commit. `BaseRepository.create()` / `update()` / `delete()` flush ngay để có ID và để lỗi ràng buộc lộ sớm, nên
  `IntegrityError` có thể xuất hiện lúc service chạy chứ không chỉ lúc commit.
- Ngoại lệ có chủ đích: `ChatService` (`text2sql`) tự commit lượt hỏi khi bắt đầu, khi dừng chờ làm rõ và khi xong,
  vì một lượt chạy lâu và trả dần qua SSE; task Celery `process_ingestion_job` tự commit trạng thái job.
- Khi một lỗi được trả về, session đã được rollback; không có thay đổi dở dang nào được lưu.

## Nhóm quyền

Quyền của extension là permission FAB trên view menu `Text to BI` (`modules/auth/services/srv_access.py`), gán qua bốn
nhóm quyền do `ensure_auth_roles()` tạo (`srv_roles.py`):

| Nhóm quyền | Permission | Được làm |
| --- | --- | --- |
| `Text to BI Viewer` | `can_view`, API `can_read` | Xem metadata của dataset được quyền đọc |
| `Text to BI Editor` | `can_view`, `can_edit`, API `can_read` / `can_write` | Tạo, sửa, xóa bản nháp metadata |
| `Text to BI Steward` | như Editor cộng `can_review` | Duyệt, thu hồi, xóa nội dung đã duyệt |
| `Text to BI Query` | `can_query`, API `can_read` / `can_write` | Hỏi dữ liệu (chat), hội thoại |

- Nhóm `Admin` của Superset qua mọi kiểm tra vai trò (`is_admin()`), và cũng được gán bốn permission trên.
- Quyền dataset của Superset luôn áp lên trên mọi nhóm quyền, kể cả Admin: `can_access_dataset` gọi
  `security_manager.raise_for_access(datasource=dataset)`; DAO của Superset lọc dataset người gọi không thấy nên nó
  trả 404 thay vì 403.
- Khi nạp extension, `entrypoint.py` khai báo view menu `Text to BI` và `text_to_bi_api` là admin-only để `superset
  init` không tự gán chúng cho Alpha, Gamma; `ensure_text_to_bi_roles()` còn gỡ chúng khỏi `Alpha`, `Gamma`,
  `Public`, `sql_lab`.
- `GET /auth/me` trả `is_admin`, `can_view`, `can_edit`, `can_query`, `can_review`; lần gọi đầu của người có quyền tạo
  nhóm quyền. Chỉ Admin gán nhóm quyền (`/auth/role-assignments`, `/auth/users/<id>/roles`).

Hàm kiểm tra dùng chung (`srv_access.py`): `require_admin()`, `require_view()`, `require_review()`,
`require_dataset_access(dataset)`, `require_edit(dataset)` (cần `can_edit` và quyền dataset),
`require_query(dataset)` (cần `can_query` và quyền dataset).

## Quyền từng mục giao diện

Trang `/text-to-bi/` chuyển người chưa đăng nhập tới trang đăng nhập và trả 403 nếu người dùng không có `can_view`
lẫn `can_query`. Frontend ẩn mục theo `canOpenSection` (`features/workspace/workspace-layout.tsx`), khớp với kiểm tra
của backend:

| Mục | Điều kiện | Kiểm tra ở backend |
| --- | --- | --- |
| Hỏi dữ liệu (`chat`) | `can_query` | `require_query` trên mọi dataset của database |
| Tri thức riêng (`own-knowledge`) | Admin | `/own-knowledge/admin/*` gọi `require_admin()` |
| Từ điển, Mô hình, Dòng dữ liệu, Tổng quan, Metric, Thuật ngữ, Quy tắc | `can_view` | Route đọc gọi `require_view()` và kiểm tra quyền dataset |

`?section=` không tồn tại hoặc người dùng không mở được thì trang mở Tổng quan nếu họ được xem, không thì mục đầu
tiên họ mở được (người chỉ có `can_query` vào thẳng Hỏi dữ liệu), rồi sửa địa chỉ cho khớp (`useAllowedSection`).

## Kiểm tra quyền theo nghiệp vụ

- **Metadata** (`data_dictionary`, `metric_management`, `glossary_management`, `expert_rule_management`): đọc cần
  `require_view()` ở route và `require_dataset_access` ở service; tạo, sửa, xóa nháp cần `require_edit(dataset)`;
  duyệt, thu hồi và xóa bản đã duyệt cần `require_review()`.
- **Business model, data lineage:** đọc cần `require_view()`; tầng dữ liệu, miền nghiệp vụ, canvas database và canvas
  lineage chỉ Admin sửa; gán dataset vào tầng, cạnh và phép biến đổi lineage cần `require_edit` trên từng dataset
  liên quan.
- **Text2SQL:** `chat`, `chat/stream` và `retrieve` nhận một `database_id`; database phải có engine PostgreSQL, có ít
  nhất một dataset, và người gọi phải qua `require_query` trên **mọi** dataset của database đó. Khi chạy SQL,
  `run_superset_read_only` kiểm tra thêm `can_execute_sql_query` trên `SQLLab`, `SQLLAB_ENABLED`, việc SQL Lab không
  bị buộc chạy bất đồng bộ, `expose_in_sqllab` của database và `raise_for_access(database=...)`. Đồng bộ chỉ mục
  (`/ingestion/sync`, `/ingestion/jobs`) chỉ Admin.
- **Hội thoại:** chỉ chủ hội thoại thấy nó (của người khác trả 404); cần `can_query` và quyền đọc ít nhất một dataset
  của database. Lượt hỏi có `dataset_id` cần `require_query` trên dataset đó; lượt có dòng kết quả mà không có dataset
  (agent truy vấn cả database, thường join nhiều dataset) cần `require_query` trên mọi dataset của database. Kiểm tra
  này chạy cả khi lưu lượt lẫn khi đọc lại, nên người mất quyền không xem lại được số liệu cũ.
- **Tri thức riêng:** chỉ được tạo qua API của agent, `POST /own-knowledge/clarifications` rồi
  `/clarifications/<id>/answer` (cần `require_view()` và permission `can_write`); khung chat không tạo tri thức riêng.
  `/own-knowledge/agent/entries*` cần `require_view()`; duyệt và đưa vào tri thức dùng chung
  (`/own-knowledge/admin/entries*`) chỉ Admin, trong mục Tri thức riêng.

## Bảng và migration

- Route đầu tiên đụng tới bảng gọi `ensure_<module>_tables()` của module trước khi dùng bảng (xem
  [kien-truc.md](kien-truc.md#migration)). Hàm chạy một lần cho mỗi process và giữ PostgreSQL advisory lock để các
  worker không migrate song song.
- Session bỏ ngỏ trên thread của LangGraph giữ lock và làm migration treo; xem quy tắc `release_thread_session` trong
  [kien-truc.md](kien-truc.md#text2sql).
