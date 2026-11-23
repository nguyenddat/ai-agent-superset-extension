# API Conversation

API class `ConversationAPI` (`resource_name="conversations"`). Base resource:
`/extensions/text-to-bi/superset-text-to-bi/conversations`.

Mọi endpoint cần phiên Superset, permission `can_read` (GET) hoặc `can_write` (ghi) trên `text_to_bi_api`, và quyền
Query của Text to BI (`can_query`, service kiểm tra). Route ghi kiểm tra header `X-CSRFToken` và commit ở route. User
lấy từ phiên; request không nhận `user_id`. `conversation_id` và `turn_id` là UUID; `result_id` có dạng
`<số>-<số>` (bước-kết quả). Quy tắc quyền trên từng lượt xem [Conversation](text-to-bi-conversation.md).

| Method và path | Request | Response thành công |
| --- | --- | --- |
| `POST /` | `{database_id: int > 0, title?: string \| null}` | 201 `{conversation}` |
| `GET /` | Query `database_id?`, `archived=false` (`true`/`false`), `q?` (tìm theo tiêu đề), `limit=50`, `offset=0` | 200 `{result: ConversationListItem[]}` |
| `GET /<conversation_id>` | Query `turns_limit=100`, `turns_offset=0` | 200 `{conversation: ConversationDetail}` |
| `PATCH /<conversation_id>` | `{title?, is_pinned?, is_archived?}`; field `null` bị bỏ qua | 200 `{conversation}` |
| `DELETE /<conversation_id>` | Không có body | 200 `{message}` |
| `GET /<conversation_id>/turns` | Query `limit=100`, `offset=0` | 200 `{turns: TurnOut[]}` |
| `GET /<conversation_id>/turns/<turn_id>` | Không có body | 200 `{turn}` |
| `DELETE /<conversation_id>/turns/<turn_id>` | Không có body | 200 `{message}` |
| `PUT /<conversation_id>/turns/<turn_id>/feedback` | `{rating: "up" \| "down", comment?: string \| null}` | 200 `{feedback}` |
| `DELETE /<conversation_id>/turns/<turn_id>/feedback` | Không có body; xóa khi chưa có cũng thành công | 200 `{message}` |
| `PUT /<conversation_id>/turns/<turn_id>/views/<result_id>` | `{chart: object}` | 200 `{view}` |
| `DELETE /<conversation_id>/turns/<turn_id>/views/<result_id>` | Không có body | 200 `{message}` |

`limit`/`turns_limit` phải từ 1 đến 500, offset không âm. Danh sách xếp hội thoại ghim trước, rồi theo
`last_message_at` mới nhất; `q` tìm không phân biệt hoa thường trong tiêu đề. Tiêu đề tối đa 2.000 ký tự theo schema, sau khi chuẩn hóa
khoảng trắng phải không rỗng và tối đa 200. Nhận xét tối đa 2.000 ký tự.

## Cấu trúc response

- `Conversation`: `id`, `database_id`, `user_id`, `title`, `is_pinned`, `is_archived`, `last_message_at`,
  `created_at`, `updated_at`, `turn_count`. `ConversationListItem` thêm `last_question` (rút gọn 120 ký tự) và
  `last_status`; `ConversationDetail` thêm `turns`.
- `TurnOut`: `id`, `conversation_id`, `sequence`, `question`, `rewritten_question`, `answer`, `flow`, `status`,
  `steps`, `results`, `rewrite`, `assumptions`, `pii`, `dataset_id`, `retry_of`, `continued_from`,
  `clarification_question`, `clarification_options`, `resume_id`, `resume_expires_at`, `error_code`, `error`,
  `duration_ms`, `model`, `feedback`, `views`, `created_at`, `updated_at`. `resume_id` chỉ có giá trị khi lượt đang chờ
  trả lời và chưa hết hạn; `error` là câu chung khi `status` là `error`.
- `feedback`: `{rating, comment, created_at, updated_at}`.
- `view`: `{result_id, chart, warnings, updated_at}`; `chart` là spec đã chuẩn hóa sau khi kiểm tra theo kết quả đã
  lưu.

Lượt mới không tạo qua resource này mà qua `POST /text2sql/chat/stream`; xem [Text2SQL API](text-to-bi-text2sql-api.md).

## Lỗi

| Status | `code` | Khi nào |
| --- | --- | --- |
| 403 | `query_permission_required` | Người gọi không có quyền Query |
| 403 | `dataset_access_required` | Lượt có hàng mà người gọi không còn truy cập dataset tạo ra nó (với lượt không có `dataset_id`: mọi dataset của database) |
| 403 | `csrf_token_invalid` | Thiếu hoặc sai CSRF token |
| 404 | `conversation_not_found` | Không có hội thoại hoặc hội thoại của user khác |
| 404 | `conversation_turn_not_found` | Lượt không thuộc hội thoại |
| 404 | `conversation_result_not_found` | `result_id` không có trong kết quả của lượt |
| 404 | `conversation_database_not_found` | Database không còn hoặc người gọi không truy cập được dataset nào trong đó |
| 404 | `dataset_not_found` | `dataset_id` của lượt không còn thấy trong Superset |
| 422 | `conversation_invalid` | UUID hoặc `result_id` sai dạng, `archived` sai, trang ngoài giới hạn, tiêu đề rỗng hoặc quá dài |
| 422 | `conversation_chart_invalid` | Biểu đồ không hợp với kết quả; `message` liệt kê lỗi |
| 422 | `invalid_request` | Body sai schema |
| 500 | `internal_error` | Lỗi không dự kiến; transaction được rollback |
