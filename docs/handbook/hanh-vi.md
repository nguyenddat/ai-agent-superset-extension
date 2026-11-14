# Hành vi chung của API

Mô tả cách backend Semantic Layer và AI Agent trả lỗi, giữ transaction và kiểm tra quyền. Mọi route mới theo đúng các
quy tắc này để client nhận cùng một kiểu phản hồi ở mọi nơi.

## Exception

API public giữa extension và bên tiêu thụ dùng success envelope `{"schema_version": 1, "result": {...}}`.
Các route và quy tắc version nằm trong [public-api-v1.md](../specs/public-api-v1.md). Lỗi giữ HTTP status cùng
`message` an toàn; API quản trị hiện có và SSE giữ giao thức hiện hành. Client từ chối version chưa hỗ trợ.

`common/exceptions/` giữ các lớp lỗi gốc. Chúng là lớp trừu tượng (khởi tạo trực tiếp sẽ ném `TypeError`); mỗi lớp
mang `status` và `message` mặc định:

| Lớp gốc | Status | Dùng khi |
| --- | --- | --- |
| `ValidationError` | 400 | Dữ liệu gửi lên phạm quy tắc; cũng là `ValueError` |
| `NotAuthorizedError` | 403 | Thiếu vai trò hoặc quyền Superset |
| `SelfApprovalError` | 403 | Người soạn tự duyệt khi cần người duyệt thứ hai |
| `NotFoundError` | 404 | Bản ghi được nêu không tồn tại |
| `ConflictError` | 409 | Xung đột trạng thái: revision đã đổi, đã có contract được duyệt |
| `TooManyRequestsError` | 429 | Vượt giới hạn số mục đang chờ duyệt |
| `ServiceUnavailableError` | 503 | Dịch vụ ngoài (OpenRouter, Semantic Layer với AI Agent) chưa sẵn sàng |

AI Agent dùng gốc `AgentError` thay cho `SemanticLayerError` và chỉ có `ValidationError`, `NotAuthorizedError`,
`NotFoundError`, `ServiceUnavailableError`.

Quy tắc:

- Mỗi module khai báo lỗi của nó trong `modules/<module>/exceptions.py`, kế thừa lớp gốc và đặt `message` mặc định.
  Lỗi của các kiểm tra dùng chung nằm trong `core/exceptions.py`; lỗi không thấy dataset, database nằm trong
  `modules/superset/exceptions.py`.
- Service và route `raise` lỗi của module; không `return self.response(4xx, …)` và không ném `ValueError` /
  `PermissionError` trần.
- Thông điệp lỗi là văn bản an toàn để hiện cho người dùng, không chứa SQL, stack trace hay chi tiết nội bộ. Thông điệp
  mới viết bằng tiếng Việt; thông điệp cũ giữ nguyên chữ vì client và test có thể so khớp.
- Lỗi do thư viện ném ra (ví dụ `IntegrityError` của SQLAlchemy) được bắt ở nơi biết nghĩa nghiệp vụ của nó và chuyển
  thành lỗi của module (`ExpertRuleValidationError("Could not save the expert rule.")`).

## Thứ tự decorator của route

```python
@expose(f"{prefix}/approve", methods=("POST",))
@protect()
@safe
@permission_name("write")
@csrf_protected        # chỉ route thay đổi dữ liệu
@rollback_on_error     # chỉ route thay đổi dữ liệu
@handle_errors         # dưới mọi decorator của Superset
@requires_metric       # nếu có: nạp đối tượng từ ID trên URL, sát hàm nhất
def approve_metric_contract(self, dataset, metric):
    ...
```

- `handle_errors` (`core/database.py`) bắt `SemanticLayerError` (AI Agent: `AgentError`), rollback session và trả
  `status` cùng `message` của lỗi. Nó phải nằm dưới `@safe` và `rollback_on_error`, vì hai decorator đó biến mọi
  exception thành 500.
- `@requires_dataset`, `@requires_metric`, `@requires_database`, `@requires_user` (`modules/superset/dependencies.py`)
  nằm dưới `handle_errors`, sát `def`: chúng lấy ID khỏi tham số URL, truyền đối tượng (`dataset`, `metric`, …) vào hàm
  và ném lỗi 404 của module `superset` để `handle_errors` trả về.
- `rollback_on_error` bắt lỗi ngoài dự kiến, ghi log, rollback và trả 500 "Could not save the change.", không lộ chi
  tiết lỗi.
- Route chỉ đọc (GET) không cần `csrf_protected` và `rollback_on_error`, nhưng vẫn có `handle_errors`.

## Transaction

- Route sở hữu transaction: nó gọi `db.session.commit()` một lần khi mọi bước đã xong. Service và repository không
  commit. Ngoại lệ duy nhất là `seed_dictionary`, tự commit để không để transaction mở cho phần tiếp theo.
- `BaseRepository.add()` và `update()` flush ngay để có ID và để lỗi ràng buộc lộ sớm. Vì vậy `IntegrityError` có thể
  xuất hiện trong lúc service chạy, không chỉ lúc commit: khối `try` bắt nó phải bao cả lời gọi service lẫn commit.
- Khi một lỗi được trả về, session đã được rollback; không có thay đổi dở dang nào được lưu.

## Quyền và CSRF

- Route thay đổi dữ liệu và màn chỉ dành cho quản trị gọi `require_admin()` ở đầu hàm; nó ném `AdminRequiredError`
  (403 "Admin access required."). Chỉ `Admin` được sửa, duyệt, thu hồi.
- Semantic Layer có hai nhóm quyền Superset (module `access_control`), dựa trên permission FAB `can_view` / `can_query`
  của view menu "Text to BI Semantic Layer":
  - Route đọc của trang quản trị (danh sách metric, thuật ngữ, expert rule, lịch sử, Data Dictionary của một dataset,
    tầng dữ liệu) gọi `require_semantic_layer_view()`: `Admin` hoặc nhóm "Semantic Layer Viewer"; thiếu quyền là 403
    `SemanticLayerViewRequiredError`.
  - Route tiêu thụ (semantic catalog, schema graph, dimension members, glossary discovery, expert rule discover, chạy
    metric, các route AI Agent ladder) gọi `require_semantic_layer_query()`: `Admin` hoặc nhóm "Semantic Layer Query";
    thiếu quyền là 403 `SemanticLayerQueryRequiredError`. `/chat/stream` của AI Agent kiểm tra cùng permission.
  - Quyền dataset của Superset vẫn áp lên trên: route đọc lọc bỏ hoặc từ chối (403) dataset người gọi không đọc được.
  - Superset tự gán mọi permission không thuộc admin-only cho Alpha và Gamma khi `superset init`; vì vậy extension khai
    báo view menu này là admin-only khi nạp và gỡ hai permission khỏi nhóm dựng sẵn khi tạo nhóm quyền.
- Route đọc dữ liệu của một dataset gọi `require_dataset(...)` rồi `require_dataset_access(dataset)` để Superset kiểm
  tra quyền đọc; thiếu quyền là 403 "Dataset and database access required.".
- Mọi route thay đổi dữ liệu dùng chung `csrf_protected` của `core/security.py`; token sai trả 403
  "CSRF token không hợp lệ." cho mọi API, kể cả `ExpertRuleAPI`.
- Duyệt thuật ngữ, rule, metric và relationship contract: khi `TEXT_TO_BI_REQUIRE_SECOND_REVIEWER = True` trong `superset_config`, người soạn
  không được tự duyệt (`SelfApprovalError`, 403). Mặc định tắt để một quản trị viên tự duyệt được.

- GET từ điển, quan hệ, schema graph và xuất file không gọi seed; metadata chưa lưu được biểu diễn bằng snapshot
  trong bộ nhớ, không thêm vào session. Preview file cũng không seed. Migration gate trên lần truy cập đầu vẫn theo
  quy tắc riêng bên dưới; không coi đó là thao tác seed thường xuyên của route đọc.
- Recheck relationship không đạt hoặc truy vấn kiểm tra lỗi sẽ bỏ duyệt và xóa người/thời điểm duyệt. Trường hợp
  truy vấn lỗi là ngoại lệ có chủ đích: route commit việc vô hiệu hóa contract rồi trả 500, tránh giữ cạnh join không
  còn bằng chứng hợp lệ. Lỗi ghi ngoài dự kiến vẫn rollback theo quy tắc chung.

## Bảng và migration

- Route đầu tiên đụng tới bảng của extension gọi `ensure_dictionary_tables()` (AI Agent: `ensure_agent_tables()`) trong
  `migrations.py`. Hàm tạo và nâng cấp bảng một lần cho mỗi process, giữ PostgreSQL advisory lock để các worker không
  chạy song song, và không thử lại trong 30 giây sau một lần lỗi.
- `ExpertRuleAPI` không chạy DDL; bảng của nó được tạo trong cùng migration đó.
