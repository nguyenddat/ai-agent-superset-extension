# API Conversation

API class: `ConversationAPI` (`resource_name="conversations"`). Đường dẫn extension là
`/extensions/text-to-bi/superset-text-to-bi/conversations`. Mọi endpoint yêu cầu phiên Superset đã đăng nhập, quyền
chung `text_to_bi_api` (`can_read` cho GET, `can_write` cho thao tác ghi) và vai trò Text to BI Query. Thao tác ghi
cần CSRF. Service chỉ truy cập hội thoại và lượt của user Superset hiện tại; request không nhận `user_id`. Phản hồi
thành công là JSON với thuộc tính như cột bên dưới; lỗi dùng envelope `{code, message}`. `conversation_id` và `turn_id`
là UUID; ID kết quả có dạng số thập phân `<step>-<result>`.

| Method và path | Quyền | Request | Phản hồi thành công |
| --- | --- | --- | --- |
| `POST /` | write + CSRF | JSON `{database_id: positive int, title?: string \| null}`; title tối đa 2000 ký tự trong schema, sau chuẩn hóa service tối đa 200 | `201 {conversation}` |
| `GET /` | read | Query: `database_id?`, `archived=false`, `q?`, `limit=50`, `offset=0`; limit trang 1–500, offset ≥0 | `200 {result: ConversationListItem[]}` |
| `GET /<conversation_id>` | read | Query: `turns_limit=100`, `turns_offset=0`; limit trang 1–500, offset ≥0 | `200 {conversation: ConversationDetail}` |
| `PATCH /<conversation_id>` | write + CSRF | JSON `{title?: string, is_pinned?: boolean, is_archived?: boolean}`; title được chuẩn hóa, tối đa 200 ký tự | `200 {conversation}` |
| `DELETE /<conversation_id>` | write + CSRF | Không có body | `200 {message}` |
| `GET /<conversation_id>/turns` | read | Query: `limit=100`, `offset=0`; limit trang 1–500, offset ≥0 | `200 {turns: TurnOut[]}` |
| `GET /<conversation_id>/turns/<turn_id>` | read | Không có body | `200 {turn}` |
| `DELETE /<conversation_id>/turns/<turn_id>` | write + CSRF | Không có body | `200 {message}` |
| `PUT /<conversation_id>/turns/<turn_id>/feedback` | write + CSRF | JSON `{rating: "up" \| "down", comment?: string \| null}`; comment tối đa 2000 ký tự | `200 {feedback}` |
| `DELETE /<conversation_id>/turns/<turn_id>/feedback` | write + CSRF | Không có body | `200 {message}` |
| `PUT /<conversation_id>/turns/<turn_id>/views/<result_id>` | write + CSRF | JSON `{chart: object}`; chart được kiểm tra theo kết quả đã lưu | `200 {view}` |
| `DELETE /<conversation_id>/turns/<turn_id>/views/<result_id>` | write + CSRF | Không có body | `200 {message}` |

Phần tử danh sách gồm metadata hội thoại, số lượt và câu hỏi/trạng thái mới nhất. Detail và turn trả trạng thái lượt,
kết quả, phản hồi và cấu hình biểu đồ đã lưu. Kết quả truy vấn lưu trữ bị giới hạn theo
`CONVERSATION_MAX_STORED_ROWS` (mặc định 200 hàng). Service từ chối truy cập hội thoại của user khác, turn thuộc hội
thoại khác, kết quả gắn với dataset ngoài Superset database của hội thoại, trạng thái không hợp lệ và ID sai định dạng.

`database_id` trong `ConversationCreate` phải là ID của Superset database. Turn mới được tạo qua route chat của
Text2SQL; resource này quản lý lịch sử và trạng thái hiển thị. Xem [Text2SQL API](text-to-bi-text2sql-api.md).
