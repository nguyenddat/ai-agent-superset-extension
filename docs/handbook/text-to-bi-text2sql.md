# Text2SQL trong Text to BI

Module `text2sql` trả lời câu hỏi bằng ngôn ngữ tự nhiên trên dữ liệu Superset: viết lại câu hỏi, tách câu hỏi con, tìm tri thức liên quan trong chỉ mục Qdrant, để agent LangGraph gọi công cụ (đọc metric, bảng, quy tắc, chạy SQL qua SQL Lab, vẽ biểu đồ, hỏi lại người dùng), rồi tổng hợp câu trả lời. Module dùng database và dataset của Superset làm catalog; không tạo model database/schema/table riêng, không đọc URI kết nối và không mở kết nối trực tiếp tới warehouse.

## Ranh giới module

- `database_id` là `dbs.id` của Superset, `dataset_id` là `tables.id`. Hiện chỉ hỗ trợ database có engine `postgresql`.
- User luôn lấy từ phiên Superset (`current_user_id()`); payload không chọn được chủ sở hữu hội thoại hay checkpoint.
- Từ điển dữ liệu, metric, thuật ngữ, quy tắc, tri thức riêng và hội thoại thuộc các module tương ứng; Text2SQL đọc qua service của chúng. Mỗi lượt chat được ghi vào module [Conversation](text-to-bi-conversation.md).
- Bảng riêng của module (schema `text_to_bi`): `text2sql_chat_checkpoints` (snapshot LangGraph của lượt đang chờ người dùng trả lời) và `text2sql_ingestion_jobs` (hàng đợi lập chỉ mục). Vector nằm trong Qdrant.

## Luồng một lượt chat

1. Route kiểm tra body (`ChatIn`) và database: database phải tồn tại, là PostgreSQL, có ít nhất một dataset, và người dùng có quyền query (`require_query`: role Text to BI Query hoặc Admin, cộng quyền đọc dataset Superset) trên **mọi** dataset của database đó.
2. `ChatService.prepare` lấy hội thoại của user (hoặc tạo mới), nhận `resume_id` nếu có, lấy 6 lượt gần nhất của hội thoại làm lịch sử, ghi lượt mới và commit. Vì API luôn biết user, `chat_history` trong body bị bỏ qua.
3. `ChatService.execute` chạy đồ thị LangGraph trong `services/chat_graph.py`: `preprocess` (LLM viết lại câu hỏi, tách câu hỏi con và phụ thuộc, phân loại ý định, tìm metric/bảng/cột/thuật ngữ/quy tắc/tri thức riêng trong Qdrant cho từng câu hỏi con) → `dispatch` → `answer_question` cho các câu hỏi con sẵn sàng (chạy song song theo phụ thuộc) → `clarify` nếu có câu hỏi con đang chờ người dùng → `synthesize` khi có nhiều câu hỏi con.
4. Mỗi câu hỏi con chạy tool agent (`agent_package/tool_agent.py`, tối đa `TEXT2SQL_AGENT_MAX_STEPS` bước) với các công cụ `get_metric`, `get_table`, `get_expert_rule`, `get_column_values`, `query_metric`, `run_sql`, `make_chart`, `ask_user`.
5. Kết quả, các bước, bảng số liệu và biểu đồ được lưu vào lượt hội thoại; lỗi được ghi thành lượt `error`.

Giá trị nhạy cảm (email, số điện thoại, CCCD, mã số thuế, tài khoản ngân hàng…) trong kết quả truy vấn được thay bằng nhãn trước khi gửi LLM (`services/pii_masker.py`, Presidio); câu trả lời và sự kiện gửi người dùng được đổi lại giá trị thật.

## Truy vấn qua Superset

SQL của `query_metric` (dựng bởi `sql_builder.py`) và `run_sql` đều đi qua `services/superset_query.run_superset_read_only`. Adapter dùng lệnh SQL Lab nội bộ của Superset, `DatabaseDAO` và `security_manager.raise_for_access`; yêu cầu quyền query của Text to BI và `can_execute_sql_query` trên `SQLLab`; `sql_guard.validate_select` chỉ nhận đúng một câu `SELECT` (có thể kèm `WITH`, `UNION`) trên các bảng thuộc dataset người dùng đọc được, chặn hàm nguy hiểm và giới hạn số dòng (`TEXT2SQL_QUERY_MAX_ROWS`). Text2SQL không nâng quyền thay người dùng. SQL Lab có cấu hình Row Level Security riêng (`RLS_IN_SQLLAB`); quyền dataset và database không đồng nghĩa với RLS được áp dụng.

## Luồng SSE `POST /text2sql/chat/stream`

Lỗi kiểm tra body, database và quyền trả JSON `{code, message}` trước khi stream bắt đầu. Sau đó phản hồi là `text/event-stream`; mỗi sự kiện là `event: <tên>` và `data: <JSON>`. Khi 10 giây không có sự kiện, server gửi dòng chú thích `: keep-alive`.

| Sự kiện | Dữ liệu | Khi nào |
| --- | --- | --- |
| `turn` | `{conversation_id, turn_id, continued_from}` | Đầu lượt, sau khi lượt được ghi |
| `preprocess` | `{rewritten_question, is_split, execution_mode, stages, questions}`; mỗi câu hỏi con có `position`, `question`, `depends_on`, `question_type`, `business_concepts`, `metrics: [{name, label}]`, `glossary`, `expert_rules`, `own_knowledge` (tên hiển thị) | Xong bước tiền xử lý |
| `question_started` | `{position, question, resumed}` | Bắt đầu trả lời một câu hỏi con |
| `tool_started` | `{position, tool, subject}` | Agent bắt đầu gọi một công cụ |
| `tool` | `{position, tool, arguments, sql, columns, rows, row_count, truncated, notes, error, result_id, fields, explanations, chart, chart_source, chart_types, display}` | Một công cụ chạy xong |
| `answer_delta` | `{position, round, final, text}` | Đoạn chữ câu trả lời đang sinh; `position` là `null` ở bước tổng hợp |
| `answer_reset` | `{position, round}` | Bỏ các đoạn đã gửi của vòng đó |
| `question_waiting` | `{position, question, options}` | Câu hỏi con dừng để hỏi lại người dùng |
| `question_answered` | `{position, question, answer, exhausted}` | Câu hỏi con có câu trả lời |
| `synthesize_started` | `{}` | Bắt đầu tổng hợp nhiều câu hỏi con |
| `answer` | `{answer}` | Câu trả lời tổng hợp |
| `clarification` | `{question, options, resume_id, expires_at}` | Lượt dừng chờ người dùng trả lời |
| `done` | `{status, answer, clarification_question, clarification_options, resume_id, resume_expires_at, conversation_id, turn_id, history_answer}` | Kết thúc lượt; `status` là `answered` hoặc `needs_clarification` |
| `error` | `{code, message}` | Lỗi trong lượt; lỗi không lường trước có `code="internal_error"` |

`POST /text2sql/chat` chạy cùng luồng nhưng trả một `ChatOut` duy nhất; frontend chỉ dùng bản stream.

### Luồng và session

- Route trả `Response` ngay; luồng `text2sql-chat-stream` chạy vòng lặp asyncio của `ChatStream`, luồng `text2sql-chat` chạy `prepare` và `execute`. Cả hai được bọc bằng `with_request_user` (`services/chat_stream.py`): nó dùng `copy_current_request_context` và chép `g.user` vào app context mới, vì security manager của Superset đọc user từ `g` khi agent liệt kê dataset được query.
- LangGraph chạy node của đồ thị và bước của tool agent trên pool thread riêng. Các node `preprocess`, `answer_question`, `synthesize` và mọi công cụ của agent được bọc bằng `release_thread_session` (`common/utils/thread_session.py`): session `db.session` do hàm mở trên pool thread được `remove()` khi hàm xong. Thiếu bước này, session của pool thread giữ transaction "idle in transaction" và khóa bảng suốt đời worker, làm `ALTER TABLE` của các hàm `ensure_*` treo và mọi truy vấn bảng đó xếp hàng sau.
- Khi client ngắt kết nối, cờ dừng được bật; lần phát sự kiện tiếp theo ném `Text2SqlClientDisconnected` để dừng lượt.

## Hỏi lại và tiếp tục (clarification/resume)

- Công cụ `ask_user` (tối đa 2 lần mỗi câu hỏi con) dừng câu hỏi con đó. Khi không còn câu hỏi con nào chạy được, node `clarify` gọi `interrupt` của LangGraph: một câu hỏi con thì gửi nguyên câu hỏi và các phương án; nhiều câu thì gộp thành danh sách đánh số, không có phương án.
- Snapshot của thread LangGraph (cùng bảng nhãn PII) được lưu vào `text2sql_chat_checkpoints` với hạn `TEXT2SQL_CLARIFICATION_TTL_MINUTES` (mặc định 1440 phút); checkpoint hết hạn bị xóa khi lưu checkpoint mới. Lượt được ghi trạng thái `needs_clarification` và trả `resume_id`.
- Lượt sau gửi câu trả lời làm `question`, kèm `resume_id` và cùng `conversation_id`. Service khóa checkpoint, kiểm tra cùng database, user và hội thoại, xóa checkpoint rồi chạy tiếp đồ thị với câu trả lời đó (áp cho mọi câu hỏi con đang chờ). Lượt mới ghi `continued_from`. Nếu chạy tiếp lỗi, checkpoint được khôi phục để thử lại. `resume_id` sai, hết hạn hoặc không thuộc user trả `404 text2sql_clarification_not_found` (với stream là sự kiện `error`).

## Biểu đồ

`GET /text2sql/chart-types` trả danh mục biểu đồ (`common/charts/catalog.py`): `version`, `palette`, `enabled` và 32 loại thuộc các nhóm Con số, So sánh, Thành phần, Xu hướng, Phân bố, Quan hệ, Dòng chảy, Bảng, mỗi loại có vai trò trường (`x`, `y`, `series`…), giới hạn dòng/chuỗi và JSON schema của tùy chọn. `TEXT2SQL_CHART_TYPES_ENABLED` (danh sách phân tách bằng dấu phẩy) giới hạn các loại được bật; `table` luôn bật; để trống là bật tất cả. Agent gợi ý biểu đồ qua `make_chart`; frontend cho đổi loại và sửa biểu đồ, kiểm tra bằng `POST /text2sql/charts/validate` và lưu lựa chọn theo lượt qua API Conversation.

## Chỉ mục Qdrant và ingestion

- Collection `TEXT2SQL_COLLECTION` (mặc định `text2sql_semantics_v1`) tại `QDRANT_URL`, vector `TEXT2SQL_EMBEDDING_DIMENSIONS` chiều từ `TEXT2SQL_EMBEDDING_MODEL` (gọi `OPENROUTER_BASE_URL/embeddings`).
- `services/index_documents.py` dựng một điểm cho mỗi thực thể, ID là `uuid5("text2sql:<topic>:<entity_id>")`, payload gồm `topic`, `entity_id`, `database_id`, `dataset_id`, `text`, model embedding và `content_hash`:

| Topic | Tài liệu |
| --- | --- |
| `table` | Dataset: nhãn, tên kỹ thuật, mô tả và grain từ từ điển dữ liệu |
| `column` | Cột: nhãn, tên, bảng, mô tả, thuật ngữ nghiệp vụ, từ đồng nghĩa, đơn vị |
| `metric` | Metric tự tạo `approved` và đang hoạt động: nhãn, tên, mô tả, miền nghiệp vụ, bảng, cột tham chiếu trong biểu thức |
| `glossary` | Thuật ngữ có bản phục vụ: định nghĩa, miền, từ đồng nghĩa, liên kết |
| `expert_rule` | Quy tắc trong discovery: miền, bảng, mô tả, điều kiện, ngoại lệ, ví dụ, thuật ngữ, metric |
| `own_knowledge` | Entry tri thức riêng đang có hiệu lực, kèm `user_id` |

- Chỉ mục chỉ gồm dataset mà người chạy sync đọc được. Khi tìm, service lọc theo database, topic và dataset người hỏi đọc được; topic `own_knowledge` lọc thêm theo `user_id` của người hỏi.
- `IngestionService.sync(database_id, topics)` dựng lại tài liệu, chỉ embed điểm có `content_hash` đổi (lô 32), xóa điểm không còn, trả `{total, indexed, unchanged, deleted}`.
- Dựng lại toàn bộ chỉ mục của một database: Admin gọi `POST /text2sql/ingestion/sync` với `{"database_id": <id>}` (bỏ `topics` là chọn mọi topic). Chưa có giao diện cho thao tác này.
- Cập nhật theo sự kiện (`services/ingestion_triggers.py`, đăng ký trong `entrypoint.py`): sau mỗi flush có thay đổi ở dataset, cột, từ điển dữ liệu, metric (kể cả `sql_metrics`), thuật ngữ, quy tắc hoặc tri thức riêng, listener ghi job `pending` theo `(database_id, topic)`. Thay đổi cấu trúc lên lịch mọi topic; metric lên lịch `metric`, `glossary`, `expert_rule`, `own_knowledge`; thuật ngữ từ `glossary` trở xuống; quy tắc `expert_rule`, `own_knowledge`; tri thức riêng chỉ `own_knowledge`. Job chỉ được gửi Celery (sau commit) khi người gây thay đổi đọc được mọi dataset của database, vì sync một phần có thể xóa nhầm điểm của dataset khác; nếu không, job ở lại `pending` không có người yêu cầu cho đến khi một thay đổi của người đủ quyền hoặc một lần enqueue thủ công gửi nó. Listener bỏ qua nếu bảng job chưa tồn tại.
- Celery task `text_to_bi.text2sql.process_ingestion_job` (`worker.py`) chạy trên `superset-worker`, đăng nhập lại bằng user yêu cầu trong `test_request_context` để quyền dataset vẫn áp dụng, claim job, sync một topic, ghi `succeeded` hoặc `failed`; thử lại tối đa `TEXT2SQL_JOB_MAX_ATTEMPTS` lần với độ trễ tăng dần. Mỗi `(database_id, topic)` chỉ có một job `pending`. Compose dùng Redis làm broker (`simulation/superset/superset_config.py`).

## Cấu hình

`core/config.py` đọc biến môi trường của tiến trình Superset (Compose nạp từ `.env`). Không ghi giá trị bí mật vào tài liệu hay mã.

| Biến | Dùng cho |
| --- | --- |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL` | Model chat (API tương thích OpenAI) và endpoint embedding |
| `QDRANT_URL`, `TEXT2SQL_COLLECTION`, `TEXT2SQL_EMBEDDING_MODEL`, `TEXT2SQL_EMBEDDING_DIMENSIONS` | Chỉ mục Qdrant |
| `TEXT2SQL_QUERY_MAX_ROWS` (200), `TEXT2SQL_AGENT_MAX_ROWS_TO_LLM` (50), `TEXT2SQL_AGENT_MAX_STEPS` (12) | Giới hạn truy vấn và agent |
| `TEXT2SQL_TIMEZONE` (`Asia/Ho_Chi_Minh`) | Ngày "hôm nay" của agent |
| `TEXT2SQL_CLARIFICATION_TTL_MINUTES` (1440) | Hạn của checkpoint hỏi lại |
| `TEXT2SQL_JOB_MAX_ATTEMPTS` (3) | Số lần thử của job lập chỉ mục |
| `TEXT2SQL_CHART_TYPES_ENABLED` | Loại biểu đồ được bật |

`config.py` còn khai báo `TEXT2SQL_RERANK_*`, `TEXT2SQL_WORKER_CONCURRENCY`, `TEXT2SQL_WORKER_POLL_SECONDS`, `TEXT2SQL_JOB_TIMEOUT_SECONDS`, `TEXT2SQL_JOB_RETENTION_DAYS`, `TEXT2SQL_TOPIC_INTERVALS`, nhưng hiện chưa có code nào dùng chúng (không có reranker, không có lịch lập chỉ mục định kỳ).

## Migration và dependencies

`ensure_text2sql_tables()` gọi `ensure_own_knowledge_tables()` (kéo theo chuỗi Expert Rule → Glossary → Metric → Business Model) và `ensure_conversation_tables()`, rồi chỉ tạo `text2sql_chat_checkpoints` và `text2sql_ingestion_jobs` dưới advisory lock `74_116_341`. Chat, chat stream và các route ingestion gọi hàm này trước khi đọc/ghi bảng. `dependencies.py` tạo service trên `superset.extensions.db.session`; client Qdrant và embedding được đóng khi xong request hoặc job.

## Giao diện

Mục **Hỏi dữ liệu** trong menu **AI Agent** (`/text-to-bi/?section=chat&database=<id>`), mở với người có quyền query (`can_query`). Trang chọn database trong thanh soạn câu hỏi, gọi `POST /text2sql/chat/stream` và hiển thị tiến trình theo sự kiện SSE: câu hỏi con, công cụ đang chạy, bảng kết quả, biểu đồ (`features/text2sql/charts`), câu trả lời đang sinh. Lượt chờ hỏi lại hiện câu hỏi và phương án; tin nhắn tiếp theo gửi kèm `resume_id`, trừ khi người dùng bỏ qua câu hỏi đó. Lịch sử hội thoại, đánh giá và lưu biểu đồ dùng API Conversation.
