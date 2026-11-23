# API Own Knowledge

API class `OwnKnowledgeAPI` (`resource_name="own-knowledge"`), đường dẫn `/extensions/text-to-bi/superset-text-to-bi/own-knowledge`. Mọi route cần phiên Superset đã đăng nhập và quyền chung `text_to_bi_api` (`can_read` cho GET, `can_write` cho thao tác ghi). Route `/clarifications` và `/agent/...` cần thêm quyền xem Text to BI (`require_view`) và quyền đọc dataset của Superset; vì cần cả `can_write`, người gọi phải là Editor, Steward, Admin, hoặc Viewer kèm Query. Route `/admin/...` cần role Superset `Admin` (`require_admin`); không có mật khẩu review. Thao tác ghi cần header `X-CSRFToken`. User và người duyệt lấy từ phiên. Lỗi trả `{code, message}`; `version` lệch hoặc idempotency key dùng lại với nội dung khác trả `409`.

| Method và path | Quyền | Request/query | Phản hồi thành công |
| --- | --- | --- | --- |
| `POST /clarifications` | write + view + CSRF | JSON `ClarificationPush` | `201 {clarification}` |
| `GET /clarifications/<clarification_id>` | read + view, chỉ của chính user | Không body | `200 {clarification}` |
| `POST /clarifications/<clarification_id>/answer` | write + view + CSRF, chỉ của chính user | JSON `{state: "confirmed" \| "dismissed", answers?: AnswerChoice[≤10]}` | `200 {result: {clarification, entries}}` |
| `GET /agent/entries` | read + view | Query bắt buộc `dataset_id` (số dương) | `200 {entries}`: entry của user hiện tại có `active_for_agent=true` |
| `PUT /agent/entries/<entry_id>` | write + view + CSRF, chỉ entry của mình | JSON `{expected_version ≥ 1, name 1–255, concept? ≤ 255, definition 1–2000}` | `200 {entry}`, entry quay về `pending` |
| `DELETE /agent/entries/<entry_id>` | write + view + CSRF, chỉ entry của mình | Không body | `200 {message}` |
| `GET /admin/entries` | read + Admin | Query tùy chọn `dataset_id`, `user_id`, `status` (`pending`, `kept_own`, `promoted`) | `200 {entries}`, chỉ entry thuộc dataset admin đọc được |
| `GET /admin/entries/<entry_id>` | read + Admin | Không body | `200 {entry}` |
| `POST /admin/entries/<entry_id>/review` | write + Admin + CSRF | JSON `{expected_version ≥ 1, action: "keep_own" \| "reopen", note? ≤ 1000}` | `200 {entry}` |
| `POST /admin/entries/<entry_id>/promote` | write + Admin + CSRF | JSON `{expected_version ≥ 1, target_kind, payload, note? ≤ 1000}` | `200 {result: {entry, target}}` |

`ClarificationPush`: `dataset_id` (> 0), `idempotency_key` (1–128), `source_session_id` và `source_question_id` tùy chọn (≤ 255), `question` (1–10.000), `missing` (1–3 loại không trùng trong `glossary`, `metric`, `expert_rule`), `proposals` (1–10). Proposal: `kind` (thuộc `missing`), `name` (1–255), `concept` (≤ 255, tùy chọn), `prompt` (1–2.000), `options` (1–10 chuỗi không trùng), `dataset_id` tùy chọn (phải trùng clarification). `AnswerChoice`: `proposal_id` thuộc clarification và đúng một trong `option_index` (0–9, nhỏ hơn số phương án) hoặc `definition` (1–2.000); mỗi proposal trả lời tối đa một lần. `confirmed` cần ít nhất một đáp án, `dismissed` không nhận đáp án.

`clarification` gồm `id`, `user_id`, `dataset_id`, `idempotency_key`, nguồn, `question`, `missing`, `status`, `proposals` (mỗi mục có `id`), `created_at`, `answered_at`. `entry` gồm `id`, `dataset_id`, `user_id`, `kind`, `name`, `concept`, `definition`, `source_clarification_id`, `source_proposal_id`, `source_question`, `review_status`, `review_note`, `reviewed_by`, `reviewed_at`, `promoted_kind`, `promoted_id`, `version`, `created_at`, `updated_at`, `active_for_agent`.

Promote: `target_kind` là `glossary`, `metric` hoặc `expert_rule`; `payload` được kiểm tra bằng `GlossaryCreate`, `MetricCreate` hoặc `RuleCreate` (xem API của module tương ứng) với `dataset_id` luôn lấy từ entry. Bản ghi đích được tạo `draft` bằng quyền của admin hiện tại; payload sai trả `422`, entry đã `promoted` trả `409`. `target` là bản ghi vừa tạo theo dạng trả về của module đích. Muốn AI dùng ngay, gọi tiếp API duyệt của module đích.
