# Conversation

Module `conversation` (`extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/conversation/`) lưu
hội thoại Hỏi dữ liệu của từng user: các lượt hỏi đáp, kết quả truy vấn, đánh giá và cấu hình biểu đồ. Module được
chuyển từ `ai-agent-superset-standalone/backend/modules/conversation`; phần chạy agent và truy vấn thuộc module
Text2SQL. Endpoint xem [API Conversation](text-to-bi-conversation-api.md).

## Dữ liệu

Ba bảng trong schema `text_to_bi`:

| Model | Bảng | Nội dung |
| --- | --- | --- |
| `Conversation` | `conversations` | `database_id` (Superset), `user_id` (`ab_user.id`), tiêu đề (tối đa 200), ghim, lưu trữ, `last_message_at` |
| `ConversationTurn` | `conversation_turns` | Câu hỏi, câu viết lại, trả lời, `flow`, `status`, các bước, kết quả, giả định, PII, `dataset_id`, clarification, `continuation`, `views` (biểu đồ đã lưu), lỗi, thời gian, model |
| `ConversationTurnFeedback` | `conversation_turn_feedback` | Đánh giá `up`/`down` và nhận xét, một dòng cho mỗi user và lượt |

- `user_id` tham chiếu `User` của `modules.auth.models`; `database_id` và `dataset_id` tham chiếu alias model Superset
  của `modules.data_dictionary.models`. Không có bảng bản sao. Xóa database hoặc user Superset xóa luôn hội thoại; xóa
  dataset đặt `dataset_id` của lượt về `null`.
- `retry_of` và `continued_from` trỏ tới lượt khác trong cùng bảng (`SET NULL` khi lượt đó bị xóa). Số thứ tự lượt
  là duy nhất trong một hội thoại.
- `status` thuộc `running`, `answered`, `needs_clarification`, `cannot_answer`, `join_ambiguous`,
  `join_not_declared`, `error`; `flow` thuộc `metric`, `dataset`, `none`.
- `ensure_conversation_tables()` tạo ba bảng với `checkfirst` dưới advisory lock riêng; không sửa bảng Superset.
  `ensure_text2sql_tables()` của Text2SQL cũng gọi hàm này. Dữ liệu hội thoại của bản standalone không được chuyển sang.

## Quy tắc

- User luôn lấy từ phiên Superset; API không nhận `user_id`. Hội thoại của user khác trả 404 như không tồn tại.
- Mọi thao tác cần quyền Query của Text to BI (`can_query`) và database phải còn, với ít nhất một dataset người gọi
  truy cập được; nếu không, trả 404 `conversation_database_not_found`. Danh sách bỏ qua hội thoại của database người
  gọi không còn thấy.
- Kết quả có hàng chỉ được trả lại cho người còn quyền truy vấn thứ đã tạo ra nó:
  - lượt có `dataset_id`: cần `require_query` trên dataset đó (quyền Query và ACL dataset Superset);
  - lượt có hàng nhưng không có `dataset_id` (agent truy vấn cả database, thường join nhiều dataset): cần
    `require_query` trên mọi dataset của database, giống điều kiện route chat nhận câu hỏi.
  Kiểm tra này chạy khi ghi lượt (`complete_turn`) và mỗi lần đọc lượt. Một lượt không qua kiểm tra làm cả request
  đọc hội thoại hoặc danh sách lượt trả 403.
- Hàng của mỗi kết quả được cắt còn `CONVERSATION_MAX_STORED_ROWS` (mặc định 200, từ 1 đến 5.000) khi lưu, kèm cờ
  `stored_truncated`.
- Biểu đồ lưu cho một kết quả được kiểm tra bằng `common/charts` theo các field và hàng đã lưu.
  `TEXT2SQL_CHART_TYPES_ENABLED` (danh sách tên, phân tách bằng dấu phẩy) giới hạn loại biểu đồ; `table` luôn được
  bật; để rỗng thì không giới hạn.
- Tiêu đề được chuẩn hóa khoảng trắng, không rỗng, tối đa 200 ký tự; hội thoại tạo từ câu hỏi đầu lấy 80 ký tự đầu
  làm tiêu đề. Câu hỏi tối đa 10.000 ký tự, nhận xét tối đa 2.000.
- Lượt lỗi chỉ trả câu chung "AI Agent không hoàn tất được câu trả lời."; chi tiết lỗi không ra client.

## Lớp module

- `models/conversation.py`: ba model và ràng buộc.
- `repositories/repo_conversation.py`: truy vấn hội thoại, lượt, đánh giá, phân trang, lịch sử.
- `services/conversation_service.py`: vòng đời lượt, quyền sở hữu, kiểm tra quyền dữ liệu, cắt hàng, lịch sử đã che
  PII, đánh giá, biểu đồ; service không commit.
- `services/result_views.py`: chuẩn hóa kết quả thành field và tùy chọn biểu đồ cho UI.
- `routes/route_conversation.py`: `ConversationAPI`, CSRF, migration, commit.
- `dependencies.py`: tạo service trên session Superset.

## Tích hợp Text2SQL

Route chat `POST /text2sql/chat/stream` dùng `ConversationService`: `start()` tạo hội thoại từ câu hỏi đầu,
`get_owned()` mở hội thoại có sẵn, `begin_turn()` tạo lượt `running`, `complete_turn()` ghi kết quả, `recent_history()`
lấy các lượt gần nhất (câu trả lời đã che PII) làm ngữ cảnh, `continuable_turn()` tiếp tục lượt đang chờ clarification.
Chat chạy graph LangGraph trên thread riêng; thread chép `g.user` của request (`with_request_user`), nên các kiểm tra
quyền trong `complete_turn()` chạy đúng với user hỏi. `answered_questions()` và `metric_usage()` có trong service
nhưng hiện chưa module nào gọi.

## Giao diện

Menu **AI Agent**, mục **Hỏi dữ liệu** (`/text-to-bi/?section=chat`), cần `can_query`. Cột lịch sử liệt kê hội thoại
chưa lưu trữ của user trên database đang chọn (tối đa 200); user mở, đổi tên, ghim hoặc xóa hội thoại tại đây. Mỗi
câu trả lời có nút đánh giá lên/xuống và có thể lưu biểu đồ đã chỉnh cho từng kết quả. Lưu trữ (`is_archived`) chưa có
nút trên UI.
