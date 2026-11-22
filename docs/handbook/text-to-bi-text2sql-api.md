# API Text2SQL

API class: `Text2SqlAPI` (`resource_name="text2sql"`). Đường dẫn extension là
`/extensions/text-to-bi/superset-text-to-bi/text2sql`. Mọi endpoint yêu cầu phiên Superset đã đăng nhập và quyền chung
`text_to_bi_api`. Thao tác đọc cần `can_read`; thao tác ghi cần `can_write`; quản trị ingestion còn yêu cầu vai trò
Superset Admin. Mọi thao tác ghi đều cần CSRF. Chat và retrieval yêu cầu vai trò Text to BI Query, quyền chạy SQL Lab và quyền truy cập
Superset vào ít nhất một dataset thuộc database được chọn. API dùng ID database và dataset dạng số của Superset; user
được xác định từ phiên hiện tại. Lỗi trả `{code, message}`, trừ endpoint phát SSE.

| Method và path | Quyền | Request/query | Phản hồi thành công |
| --- | --- | --- | --- |
| `POST /chat` | write + CSRF + Query | JSON `{database_id, question, conversation_id?, resume_id?, chat_history?: [{question, answer?}]}`; `question` 1–2000 ký tự, tối đa 50 lượt trong history | `200 {result: ChatOut}` |
| `POST /chat/stream` | write + CSRF + Query | Cùng JSON `ChatIn` | `200 text/event-stream`; SSE có tên sự kiện cho nội dung/công cụ từng bước, kết quả cuối hoặc lỗi |
| `GET /chart-types` | read | Không có body | `200 {result: danh mục loại biểu đồ}` |
| `POST /charts/validate` | write + CSRF | JSON `{chart: object, fields: FieldOut[≤100], rows: array[≤1000], rows_complete?: boolean}` | `200 {chart, warnings, chart_types}` |
| `POST /retrieve` | read + Query | JSON `{database_id, question: 1–2000 ký tự, k?: 1–10}`; mặc định `k=5` | `200 {candidates: CandidateOut[]}` |
| `POST /ingestion/sync` | write + Admin + CSRF | JSON `{database_id, topics?: string[]}` | `200 {result: {database_id, topics, total, indexed, unchanged, deleted}}` |
| `POST /ingestion/jobs` | write + Admin + CSRF | JSON `{database_id, topics?: string[]}` | `202 {database_id, topics}` |
| `GET /ingestion/jobs` | read + Admin | Query tùy chọn: `database_id`, `status`; `limit=50` (1–200) | `200 {result: JobOut[]}` |

`database_id` phải là ID dương của Superset database. Chat/retrieve hiện chỉ hỗ trợ database PostgreSQL trong Superset và
yêu cầu ít nhất một dataset người dùng được phép đọc trên database đó. Hai endpoint kiểm tra quyền dataset và SQL Lab;
SQL do agent tạo chạy qua Superset SQL Lab dưới dạng một câu `SELECT` chỉ đọc, có allowlist bảng và giới hạn số hàng.
Quyền SQL Lab cụ thể và hành vi row-level security còn tùy cấu hình Superset.

Các topic được hỗ trợ: `table`, `column`, `metric`, `glossary`, `expert_rule`, `own_knowledge`. Bỏ `topics` nghĩa là
chọn tất cả. Sync trực tiếp chạy đồng bộ, dùng cho lần index đầu hoặc thao tác vận hành có kiểm soát. Enqueue job trả
ngay sau khi ghi hàng đợi; Celery xử lý bất đồng bộ. Thay đổi Superset dataset/cột hoặc từ điển, metric, glossary,
expert rule, own knowledge của Text to BI sẽ enqueue event job trong cùng transaction metadata. Thay đổi cấu trúc lên
lịch mọi topic vì tài liệu ngữ nghĩa phụ thuộc cấu trúc dataset/cột. Extension chỉ gửi job tới
`process_ingestion_job` sau commit. Việc gửi chỉ diễn ra khi user gây ra thay đổi truy cập được mọi dataset trong
database: index một phần có thể xóa nhầm point của dataset khác trong index dùng chung. Nếu user không có đủ quyền,
event job vẫn được lưu nhưng không gắn requester và giữ trạng thái chờ; thay đổi tương ứng sau đó từ user có quyền đầy
đủ sẽ cập nhật requester và gửi job. Nếu gửi thất bại, job còn ở trạng thái chờ và sẽ được thử gửi lại khi có thay đổi
metadata phù hợp tiếp theo. Listener bỏ qua enqueue nếu bảng queue chưa tồn tại; chat, chat stream và các endpoint
ingestion sẽ tạo bảng module khi cần. Nếu thay đổi xảy ra trước khi queue được khởi tạo, sau khi queue đã được migrate,
hãy gọi `POST /ingestion/sync` chỉ với `database_id` (bỏ `topics`) để chạy sync đầy đủ cho tất cả topic.

`ChatOut` gồm answer/status, thông tin clarification và resume tùy chọn, ID conversation/turn, preprocessing và câu trả
lời từng câu hỏi. `JobOut` gồm ID job, database, topic, source, status, số lần thử, thời điểm, lỗi và kết quả. Trạng
thái job hợp lệ: `pending`, `running`, `succeeded`, `failed`, `superseded`; source gồm event, schedule, manual.
