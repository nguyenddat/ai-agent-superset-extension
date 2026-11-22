# Text2SQL trong Text to BI

Module `text2sql` chuyển luồng hỏi đáp dữ liệu từ standalone vào extension. Module dùng database và dataset của Superset làm catalog chuẩn; không tạo model database/schema/table riêng, không đọc URI đã giải mã và không mở kết nối trực tiếp tới warehouse.

## Ranh giới module

- `database_id` là khóa số của `superset.models.core.Database`; `dataset_id` là khóa số của `SqlaTable` do Superset quản lý.
- User được lấy từ phiên đăng nhập Superset bằng `current_user_id()`. Không nhận `user_id` từ payload để xác định chủ sở hữu conversation hoặc checkpoint.
- Từ điển cột, metric, glossary, expert rule, own knowledge và conversation được lấy từ các module extension hiện có. Module Text2SQL không định nghĩa lại các bảng nghiệp vụ đó.
- `ChatCheckpoint` và `IngestionJob` là hai bảng riêng của module, lưu checkpoint làm rõ câu hỏi có thời hạn và trạng thái lập chỉ mục. Migration chỉ tạo hai bảng này.
- Vector và payload tìm kiếm nằm trong Qdrant; cấu hình kết nối, collection, kích thước embedding và giới hạn truy vấn lấy từ `core/config.py`.

## Thực thi truy vấn qua Superset

Truy vấn SQL do agent sinh phải qua `services/superset_query.run_superset_read_only`. Adapter dùng SQL Lab command nội bộ của Superset 6.1, `DatabaseDAO`, quyền thực thi SQL Lab và quyền truy cập database của Superset. Adapter chỉ chấp nhận một câu `SELECT`, chặn mutation, Jinja template và chạy đồng bộ với giới hạn dòng. Không dùng `create_engine`, SQLAlchemy engine riêng hay giải mã `Database.database_name`/URI để kết nối.

Trước khi chat hoặc retrieve, API xác nhận database Superset và quyền `Text to BI Query` cùng quyền truy cập các dataset người dùng được phép đọc. Cả SQL tính metric và SQL tự sinh đều đi qua `run_superset_read_only`, adapter gọi SQL Lab command đồng bộ của Superset. Adapter kiểm tra lại bảng theo các dataset đọc được, chỉ nhận một `SELECT`, giới hạn số dòng và kiểm tra quyền `can_execute_sql_query` cùng quyền database của Superset. Nếu Superset không cho user truy cập SQL Lab hoặc database, Text2SQL không nâng quyền thay user. Bản hiện tại hỗ trợ PostgreSQL vì SQL builder và SQL guard của standalone dùng dialect này.

SQL Lab có thể cấu hình riêng về Row Level Security. Cần kiểm tra cấu hình `RLS_IN_SQLLAB` của môi trường triển khai; quyền dataset và quyền database không đồng nghĩa với bảo đảm RLS của SQL Lab.

## API

Các endpoint được đăng ký qua Flask-AppBuilder `Text2SqlAPI`, dùng class permission chung `text_to_bi_api`. Quyền vai trò Text to BI và ACL dataset được kiểm tra ở service/route theo nghiệp vụ.

| Method | Path | Mục đích |
| --- | --- | --- |
| `POST` | `/api/v1/text2sql/chat` | Hỏi đáp theo database Superset, tùy chọn conversation và resume ID |
| `POST` | `/api/v1/text2sql/chat/stream` | Cùng luồng hỏi đáp, phát sự kiện SSE |
| `GET` | `/api/v1/text2sql/chart-types` | Danh mục loại biểu đồ được bật |
| `POST` | `/api/v1/text2sql/charts/validate` | Kiểm tra cấu hình biểu đồ với fields và rows |
| `POST` | `/api/v1/text2sql/retrieve` | Tìm metric ứng viên theo câu hỏi |
| `POST` | `/api/v1/text2sql/ingestion/sync` | Đồng bộ catalog vào Qdrant; chỉ Admin |
| `POST` | `/api/v1/text2sql/ingestion/jobs` | Đưa các topic vào hàng đợi; chỉ Admin |
| `GET` | `/api/v1/text2sql/ingestion/jobs` | Xem trạng thái job; chỉ Admin |

Request chat chỉ nhận `database_id`, câu hỏi, lịch sử tùy chọn, `conversation_id` và `resume_id`; danh tính người dùng luôn lấy từ phiên Superset. Payload cần được validate bằng Pydantic schema trước khi gọi service. Các thao tác ghi dùng CSRF và transaction decorator theo handbook chung.

## Index và ingestion

`IngestionService` dựng tài liệu từ dataset Superset và metadata hiện có, embed theo lô, cập nhật Qdrant theo `database_id` và xóa point cũ của topic đã đồng bộ. Không đưa credentials hay URI kết nối nguồn vào payload index. Topic được kiểm tra theo `utils/topics.py`.

`IngestionJob` theo dõi enqueue, claim, retry và kết quả. Endpoint enqueue commit job cùng user Superset yêu cầu trước rồi dispatch Celery task `text_to_bi.text2sql.process_ingestion_job`. Task chạy trong Flask app context và khôi phục danh tính user yêu cầu để các kiểm tra quyền dataset vẫn được áp dụng; task claim job, cập nhật trạng thái và retry theo cấu hình số lần thử. Qdrant và embedding client được đóng sau tác vụ. Extension entrypoint đăng ký task với `celery_app` của Superset. Compose phát triển có Redis broker, Qdrant và Superset Celery worker; môi trường triển khai khác cần cấu hình cùng broker và chạy worker Superset. Không khởi tạo daemon worker trong tiến trình web. Endpoint đồng bộ trực tiếp dành cho Admin và dùng cho lần index đầu hoặc thao tác vận hành có kiểm soát.

## Migration và dependencies

Gọi `ensure_text2sql_tables()` trước khi đọc/ghi checkpoint hoặc job. Migration gọi migration của module Conversation trước để đảm bảo các bảng được tham chiếu, sau đó chỉ tạo `text2sql_chat_checkpoints` và `text2sql_ingestion_jobs` trong schema `text_to_bi`. Superset vẫn sở hữu bảng `dbs`, `tables`, `columns` và người dùng; Text2SQL không migrate các bảng đó.

Dependencies được tạo qua `modules/text2sql/dependencies.py`; session lấy từ `superset.extensions.db.session`. Qdrant và embedding client được đóng sau tác vụ ngắn hoặc trong factory của luồng chat. Cấu hình OpenRouter dùng settings dùng chung, không đọc biến môi trường trực tiếp trong module.

## Kiểm tra thay đổi

Khi sửa Text2SQL, rà lại import module standalone, xác nhận không còn `DatabaseConnection`, `DatabaseSchema`, `DatabaseTable`, `create_engine` hoặc đọc URI trong module, và kiểm tra đường truy vấn đi qua Superset. Không chạy test nếu yêu cầu công việc không bao gồm xác minh bằng test; khi cần xác minh tương thích, dùng quy trình Superset 6.1 trong handbook repository.
