# Own Knowledge

`own_knowledge` giữ "tri thức riêng": cách một người dùng hiểu một khái niệm nghiệp vụ mà kho chung (metric, thuật ngữ, quy tắc) chưa có. Agent hỏi lại người dùng bằng một clarification, người dùng xác nhận định nghĩa, định nghĩa thành entry riêng của người đó. Admin xem các entry ở mục Tri thức riêng, rồi giữ riêng hoặc đưa vào kho chung. Module được đối chiếu với `ai-agent-superset-standalone/backend/modules/own_knowledge`.

## Nguồn tạo entry

Entry chỉ sinh ra qua API agent: `POST /own-knowledge/clarifications` tạo câu hỏi làm rõ kèm các đề xuất, rồi `POST /own-knowledge/clarifications/<id>/answer` với `state="confirmed"` ghi đáp án thành entry. Luồng chat Text2SQL hiện không gọi hai API này, và giao diện không có form tạo entry; một agent hoặc client bên ngoài phải gọi chúng bằng phiên Superset của chính người dùng. Entry gắn với user của phiên, request không chọn được chủ sở hữu.

## Dữ liệu sở hữu

Ba model trong schema `text_to_bi`, khóa ngoại tới `SupersetDataset` (`tables`) và `User` (`ab_user`, import từ `modules.auth.models`):

- `OwnClarification` (`own_knowledge_clarifications`): `dataset_id`, `user_id`, `idempotency_key`, `source_session_id`, `source_question_id` (chuỗi tự do), `question`, `missing`, `status` (`pending`, `confirmed`, `dismissed`), fingerprint của request và câu trả lời, `confirmed_entry_ids`, `answered_at`. Duy nhất theo `(dataset_id, user_id, idempotency_key)`.
- `OwnProposal` (`own_knowledge_proposals`): `kind` (`glossary`, `metric`, `expert_rule`), `name`, `concept`, `prompt`, `options`, `dataset_id` tùy chọn. Duy nhất theo `(clarification_id, kind, normalized_name)`.
- `OwnKnowledgeEntry` (`own_knowledge_entries`): `dataset_id`, `user_id`, `kind`, `name`, `concept`, `definition`, `version`, nguồn (clarification, proposal), `review_status` (`pending`, `kept_own`, `promoted`), `review_note`, `reviewed_by`, `reviewed_at`, `promoted_kind`, `promoted_id`. Duy nhất theo `(dataset_id, user_id, kind, normalized_name)`.

## Vòng đời

- Tạo clarification idempotent: gửi lại cùng `idempotency_key` với cùng nội dung trả clarification cũ; cùng key khác nội dung trả `409`. Loại trong `missing` không trùng; mỗi proposal phải thuộc một loại trong `missing`, không trùng tên trong cùng loại, phương án không trùng; `dataset_id` của proposal (nếu có) phải trùng clarification.
- Trả lời: `confirmed` cần ít nhất một đáp án, mỗi đáp án chọn một phương án (`option_index`) hoặc tự nhập `definition`; `dismissed` không nhận đáp án. Gửi lại đúng câu trả lời cũ là idempotent; gửi nội dung khác sau khi đã trả lời trả `409`.
- Xác nhận tạo entry mới, hoặc cập nhật entry cùng `(dataset, user, kind, tên)` và tăng `version`. Mọi lần xác nhận lại hoặc người dùng tự sửa entry đều đưa entry về `pending` và xóa thông tin review/promote cũ.
- Admin `keep_own` đặt `kept_own`; `reopen` đưa về `pending`. Promote tạo bản ghi `draft` trong module đích qua service của nó (`GlossaryService.create_term`, `MetricService.create_metric`, `ExpertRuleService.create_rule`), luôn trên dataset của entry, rồi đặt `promoted` cùng `promoted_kind`, `promoted_id`. Mọi thao tác của admin và của người dùng trên entry cần `expected_version` khớp, nếu không trả `409`.
- Entry được dùng cho agent (`active_for_agent`) trừ khi đã promote và bản ghi đích đang có hiệu lực: thuật ngữ có bản phục vụ, metric `approved` và đang hoạt động, quy tắc nằm trong discovery. Nếu bản ghi chung bị xóa, thu hồi hoặc ngừng hoạt động, entry riêng được dùng lại.
- Text2SQL lập chỉ mục entry đang có hiệu lực vào topic `own_knowledge` của Qdrant với `user_id`, và chỉ tìm entry của chính người hỏi. Mọi thay đổi trên `own_knowledge_entries` tạo job lập chỉ mục topic này.

## Duyệt bằng role Admin

Bản standalone dùng mật khẩu review và API key riêng; extension thay bằng phiên Superset. Mọi route `/admin/...` gọi `require_admin()` (role Superset `Admin`), người duyệt được ghi từ phiên hiện tại. Danh sách admin chỉ trả entry thuộc dataset mà admin đọc được trong Superset.

## Lớp module

- `models/own_knowledge.py`: ba model.
- `repositories/own_knowledge_repository.py`: truy vấn, khóa dòng, tìm theo key và tên, danh sách review.
- `services/own_knowledge_service.py`: kiểm tra dữ liệu, idempotency, trả lời, review, promote, `active_for_agent`; không đọc request, không commit.
- `dependencies.py`: nối repository và service với `superset.extensions.db.session`.
- `routes/route_own_knowledge.py`: `OwnKnowledgeAPI`, kiểm tra body, quyền, CSRF, commit.
- `migrations.py`: `ensure_own_knowledge_tables()` gọi `ensure_expert_rule_tables()` (kéo theo Glossary, Metric, Business Model), rồi tạo ba bảng Own Knowledge dưới advisory lock riêng `74_116_311`. Không tạo hay sửa bảng Superset.

## API

Resource `/extensions/text-to-bi/superset-text-to-bi/own-knowledge`; chi tiết ở [API Own Knowledge](text-to-bi-own-knowledge-api.md).

| Method | Path | Mục đích |
| --- | --- | --- |
| POST | `/clarifications` | Tạo clarification idempotent cho user hiện tại |
| GET | `/clarifications/<id>` | Xem clarification của chính user |
| POST | `/clarifications/<id>/answer` | Xác nhận hoặc bỏ qua clarification |
| GET | `/agent/entries?dataset_id=...` | Entry đang có hiệu lực của user hiện tại trên dataset |
| PUT | `/agent/entries/<id>` | User sửa entry của mình |
| DELETE | `/agent/entries/<id>` | User xóa entry của mình |
| GET | `/admin/entries` | Danh sách cho Admin, lọc theo dataset, trạng thái, user |
| GET | `/admin/entries/<id>` | Xem một entry |
| POST | `/admin/entries/<id>/review` | Giữ riêng hoặc mở lại |
| POST | `/admin/entries/<id>/promote` | Đưa vào kho chung qua module đích |

Route của user cần quyền xem Text to BI và quyền đọc dataset; route admin cần role Admin. Ghi cần `can_write` của `text_to_bi_api` và CSRF.

## Giao diện

Mục **Tri thức riêng** trong menu **AI Agent** (`/text-to-bi/?section=own-knowledge&database=<id>`), chỉ hiện với Admin. Trang chọn database, đọc `GET /admin/entries` và giữ các entry thuộc dataset của database đó. Bốn ô thống kê: Chờ duyệt, Chờ duyệt có mâu thuẫn, Chờ duyệt có bản trùng, Người dùng đóng góp; bộ lọc trạng thái, loại, bảng và công tắc "Chỉ mục trùng hoặc mâu thuẫn". Frontend tự so sánh entry với metric, thuật ngữ, quy tắc trong cùng dataset và với entry của người dùng khác (backend chỉ chặn trùng tên trong entry của cùng một user). Khung chi tiết có Giữ riêng, Mở lại và Đưa vào kho; form đưa vào kho mở editor của module đích với nội dung của entry, có tùy chọn "Duyệt luôn để AI dùng ngay" (gọi API duyệt của module đích sau khi promote, cần quyền review). Tên người dùng lấy từ `GET /auth/role-assignments`. Thẻ **Tri thức riêng của người dùng** ở mục Tổng quan cũng chỉ hiện với Admin.

## Hạn chế đã biết

- Form đưa metric vào kho (`features/own-knowledge/metric-promotion.tsx`) là bản sao form tạo của editor metric, vì `MetricEditor` chưa có chế độ promote; sửa form metric thì phải sửa cả hai chỗ.
- Chưa có luồng nào trong extension tạo clarification; entry chỉ có khi client gọi API agent.
