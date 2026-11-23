# API Text2SQL

API class `Text2SqlAPI` (`resource_name="text2sql"`), đường dẫn `/extensions/text-to-bi/superset-text-to-bi/text2sql`. Mọi endpoint cần phiên Superset đã đăng nhập và quyền chung `text_to_bi_api` (`can_read` cho `GET /chart-types`, `GET /ingestion/jobs`, `POST /retrieve`; `can_write` cho các POST còn lại). Endpoint ghi có CSRF cần header `X-CSRFToken`. User lấy từ phiên. Lỗi trả `{code, message}`; với `/chat/stream`, lỗi sau khi stream đã mở đến dưới dạng sự kiện `error`.

"Query trên database" nghĩa là: database tồn tại, engine `postgresql`, có ít nhất một dataset, và người dùng qua `require_query` (role Text to BI Query hoặc Admin, cộng quyền đọc dataset Superset) trên mọi dataset của database. Truy vấn thật còn cần `can_execute_sql_query` trên `SQLLab` và quyền database của Superset.

| Method và path | Quyền | Request/query | Phản hồi thành công |
| --- | --- | --- | --- |
| `POST /chat` | write + CSRF + query trên database | JSON `ChatIn` | `200 {result: ChatOut}` |
| `POST /chat/stream` | write + CSRF + query trên database | JSON `ChatIn` | `200 text/event-stream`; sự kiện xem [Text2SQL](text-to-bi-text2sql.md#luồng-sse-post-text2sqlchatstream) |
| `GET /chart-types` | read | Không body | `200 {result: {version, palette, enabled, types}}` |
| `POST /charts/validate` | write + CSRF | JSON `{chart: object, fields: FieldOut[≤100], rows: array[≤1000], rows_complete?: boolean = true}` | `200 {chart, warnings, chart_types}`; spec sai trả `422 text2sql_chart_invalid`, `message` liệt kê từng lỗi |
| `POST /retrieve` | read + query trên database | JSON `{database_id, question: 1–2000, k?: 1–10 = 5}` | `200 {candidates: [{metric_id, table_id, name, label, description, score, matched_topics}]}` |
| `POST /ingestion/sync` | write + CSRF + Admin + query trên database | JSON `{database_id, topics?: string[]}` | `200 {result: {database_id, topics, total, indexed, unchanged, deleted}}` |
| `POST /ingestion/jobs` | write + CSRF + Admin + query trên database | JSON `{database_id, topics?: string[]}` | `202 {database_id, topics}` |
| `GET /ingestion/jobs` | read + Admin | Query tùy chọn `database_id` (kiểm tra như query trên database), `status`, `limit` (1–200, mặc định 50) | `200 {result: JobOut[]}`, mới nhất trước |

`ChatIn`: `database_id` (> 0), `question` (1–2000, không chỉ khoảng trắng), `conversation_id` (UUID, tùy chọn: thêm lượt vào hội thoại của user trên cùng database; bỏ trống thì tạo hội thoại mới), `resume_id` (UUID, tùy chọn: tiếp tục lượt đang chờ hỏi lại, khi đó `question` là câu trả lời), `chat_history` (≤ 50 mục `{question, answer?}`; bị bỏ qua vì backend đọc lịch sử từ hội thoại đã lưu).

`ChatOut`: `answer`, `status` (`answered` hoặc `needs_clarification`), `clarification_question`, `clarification_options`, `resume_id`, `resume_expires_at`, `conversation_id`, `turn_id`, `history_answer` (câu trả lời còn nhãn PII, dùng cho bước viết lại câu hỏi ở lượt sau), `preprocess` (câu hỏi viết lại, câu hỏi con, giai đoạn chạy, tri thức tìm được) và `answers` (mỗi câu hỏi con: `position`, `question`, `answer`, `exhausted`, `steps` gồm SQL, cột, dòng, giải thích, biểu đồ).

Topic hợp lệ: `table`, `column`, `metric`, `glossary`, `expert_rule`, `own_knowledge`; bỏ `topics` là chọn tất cả, topic lạ trả `422`. `/ingestion/sync` chạy đồng bộ trong request; dùng nó để dựng lại toàn bộ chỉ mục Qdrant của một database (`{"database_id": <id>}`). `/ingestion/jobs` ghi job `manual` cho từng topic (gộp với job `pending` sẵn có của cùng database và topic), commit, rồi gửi mọi job `pending` của các topic đó tới Celery task `text_to_bi.text2sql.process_ingestion_job`.

`JobOut`: `id`, `database_id`, `topic`, `source` (`event`, `schedule`, `manual`), `status` (`pending`, `running`, `succeeded`, `failed`, `superseded`), `attempts`, `run_after`, `started_at`, `finished_at`, `last_error`, `result`, `created_at`. Job `event` sinh tự động khi metadata thay đổi; quy tắc tạo và gửi job xem [Text2SQL](text-to-bi-text2sql.md#chỉ-mục-qdrant-và-ingestion). Hiện không có code nào tạo job `schedule`.
