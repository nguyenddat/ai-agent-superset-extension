# API Own Knowledge

API class: `OwnKnowledgeAPI` (`resource_name="own-knowledge"`). Đường dẫn extension là
`/extensions/text-to-bi/superset-text-to-bi/own-knowledge`. Mọi thao tác yêu cầu phiên Superset đã đăng nhập và quyền
chung `text_to_bi_api` (`can_read` cho GET, `can_write` cho thao tác ghi). Endpoint của user còn yêu cầu quyền xem
Text to BI và quyền truy cập Superset dataset; endpoint admin để review yêu cầu vai trò Superset Admin. Thao tác ghi
cần CSRF. ID user và reviewer lấy từ phiên hiện tại. Phản hồi thành công là JSON với thuộc tính ở cột dưới đây; lỗi
dùng `{code, message}`.

| Method và path | Quyền | Request/query | Phản hồi thành công |
| --- | --- | --- | --- |
| `POST /clarifications` | write + view + CSRF | JSON: `dataset_id` số dương; `idempotency_key` 1–128 ký tự; source ID tùy chọn tối đa 255; `question` 1–10000 ký tự; `missing` gồm 1–3 loại không trùng; `proposals` gồm 1–10 mục | `201 {clarification}` |
| `GET /clarifications/<clarification_id>` | read + view | Không có body | `200 {clarification}` |
| `POST /clarifications/<clarification_id>/answer` | write + view + CSRF | JSON `{state: "confirmed" \| "dismissed", answers?: [...]}`; xác nhận cần câu trả lời, bỏ qua không nhận câu trả lời | `200 {result: {clarification, entries}}` |
| `GET /agent/entries` | read + view | Query: bắt buộc `dataset_id` số dương | `200 {entries: EntryOut[]}` |
| `PUT /agent/entries/<entry_id>` | write + view + CSRF | JSON `{expected_version: số nguyên dương, name: 1–255 ký tự, concept?: string \| null (tối đa 255), definition: 1–2000 ký tự}` | `200 {entry}` |
| `DELETE /agent/entries/<entry_id>` | write + view + CSRF | Không có body | `200 {message}` |
| `GET /admin/entries` | read + Admin | Query tùy chọn: `dataset_id`, `user_id`, `status` | `200 {entries: EntryOut[]}` |
| `GET /admin/entries/<entry_id>` | read + Admin | Không có body | `200 {entry}` |
| `POST /admin/entries/<entry_id>/review` | write + Admin + CSRF | JSON `{expected_version: số nguyên dương, action: "keep_own" \| "reopen", note?: string \| null (tối đa 1000)}` | `200 {entry}` |
| `POST /admin/entries/<entry_id>/promote` | write + Admin + CSRF | JSON `{expected_version: số nguyên dương, target_kind: kind, payload: object, note?: string \| null (tối đa 1000)}` | `200 {result: {entry, target}}` |

Các loại kiến thức là `glossary`, `metric`, `expert_rule`. Một proposal có `kind`, `name` (1–255 ký tự), `concept`
tùy chọn (tối đa 255), `prompt` (1–2000), `options` (1–10 chuỗi) và `dataset_id` dương tùy chọn. Mỗi câu trả lời
chỉ rõ `proposal_id` và cung cấp đúng một trong `option_index` (0–9) hoặc `definition` tự nhập (1–2000 ký tự).
Proposal được chọn phải thuộc clarification tương ứng; các lựa chọn không được trùng nhau.

Tạo clarification có tính idempotent theo `(dataset_id, user hiện tại, idempotency_key)`. Agent chỉ liệt kê, sửa hoặc
xóa entry của user hiện tại. Thao tác cập nhật, admin review và promote dùng `expected_version` để phát hiện dữ liệu
đã thay đổi đồng thời. `status` của danh sách admin chỉ nhận `pending`, `kept_own` hoặc `promoted`. Khi promote,
payload được kiểm tra bằng schema của Glossary, Metric hoặc Expert Rule đích; entry own knowledge vẫn liên kết với bản
ghi được promote.
