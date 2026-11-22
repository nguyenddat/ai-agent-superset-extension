# Conversation

`conversation` lưu hội thoại Text to BI, các lượt hỏi đáp, kết quả, phản hồi và cấu hình biểu đồ của user. Module được chuyển từ `ai-agent-superset-standalone/backend/modules/conversation`; phần điều phối AI/query vẫn thuộc module Text2SQL.

## Model và Superset

- `Conversation`, `ConversationTurn` và `ConversationTurnFeedback` là model riêng trong schema `text_to_bi`.
- `Conversation.user_id` và feedback `user_id` tham chiếu `User` do `modules.auth.models` sở hữu (`ab_user.id`). API không nhận ID user từ client.
- `Conversation.database_id` tham chiếu `SupersetDatabase` và `ConversationTurn.dataset_id` tham chiếu `SupersetDataset` do `modules.data_dictionary.models` export. Đây là model alias của Superset, không có bảng bản sao.
- `retry_of` và `continued_from` tự tham chiếu lượt khác trong cùng bảng conversation turns. Khi xóa parent/turn, FK CASCADE/SET NULL giữ quan hệ nhất quán.

Kết quả JSON được giới hạn số hàng lưu theo `CONVERSATION_MAX_STORED_ROWS` (mặc định 200). Cấu hình biểu đồ dùng `TEXT2SQL_CHART_TYPES_ENABLED`; `table` luôn được bật. Các helper kiểm tra, chuẩn hóa và gợi ý chart dùng chung ở `common/charts`.

## Lớp module

- `models/conversation.py`: ba model, trạng thái lượt và ràng buộc feedback.
- `repositories/repo_conversation.py`: truy vấn hội thoại, turn, feedback, phân trang, lịch sử và metric usage.
- `services/conversation_service.py`: vòng đời turn, ownership, giới hạn dữ liệu lưu, history đã che PII, feedback và chart view; service không commit transaction.
- `services/result_views.py`: chuẩn hóa kết quả thành field/chart options dùng bởi UI.
- `dependencies.py`: nối service với session Superset.
- `routes/route_conversation.py`: API Flask-AppBuilder, CSRF, migration và transaction.
- `migrations.py`: tạo riêng ba bảng module dưới advisory lock; không sửa bảng Superset.

## API

Resource: `/extensions/text-to-bi/superset-text-to-bi/conversations`.

| Method | Path | Mục đích |
| --- | --- | --- |
| POST | `/` | Tạo hội thoại theo `database_id` Superset |
| GET | `/` | Liệt kê hội thoại của user hiện tại, lọc database/archive/tên và phân trang |
| GET/PATCH/DELETE | `/<conversation_id>` | Đọc, đổi tiêu đề/pin/archive hoặc xóa hội thoại của chính user |
| GET | `/<conversation_id>/turns` | Liệt kê lượt hỏi đáp |
| GET/DELETE | `/<conversation_id>/turns/<turn_id>` | Đọc hoặc xóa lượt thuộc hội thoại |
| PUT/DELETE | `/<conversation_id>/turns/<turn_id>/feedback` | Ghi hoặc xóa đánh giá up/down |
| PUT/DELETE | `/<conversation_id>/turns/<turn_id>/views/<result_id>` | Lưu hoặc xóa cấu hình biểu đồ đã validate |

Các route ghi yêu cầu CSRF và commit transaction ở route. User luôn lấy từ phiên Superset. Nội dung lượt có `dataset_id` chỉ được trả về nếu user còn quyền Query Text to BI và quyền truy cập dataset Superset đó.

## Tích hợp Text2SQL

Text2SQL gọi `ConversationService.start()` để tạo hội thoại từ câu hỏi đầu, `begin_turn()` trước khi xử lý, `complete_turn()` khi có kết quả, và `recent_history()`/`continuable_turn()` khi cần ngữ cảnh hoặc tiếp tục lượt clarification. `answered_questions()` và `metric_usage()` hỗ trợ gợi ý câu hỏi/metric. Caller không được nhận `user_id` từ payload; dùng owner từ request Superset.

## Migration

`ensure_conversation_tables()` chỉ tạo bảng conversation, turn và feedback. Model imports Superset user/database/dataset owners trước khi migration chạy. Không có bảng `database_connection` riêng; `database_id` là ID số Superset. Dữ liệu conversation cũ của standalone không tự migrate.
