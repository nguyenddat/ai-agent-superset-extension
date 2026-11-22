# Own Knowledge

`own_knowledge` ghi nhận khái niệm nghiệp vụ còn thiếu dưới dạng câu hỏi làm rõ, cho người dùng xác nhận định nghĩa gợi ý, lưu thành tri thức cá nhân và cho Admin giữ riêng hoặc chuyển thành glossary, metric hay expert rule dùng chung. Module được đối chiếu với `ai-agent-superset-standalone/backend/modules/own_knowledge`.

## Ánh xạ sang Superset và quyền sở hữu model

- Extension sở hữu ba model `OwnClarification`, `OwnProposal` và `OwnKnowledgeEntry` trong schema `text_to_bi`.
- Phạm vi `connection_id`/`table_id` của standalone được ánh xạ sang `dataset_id` Superset. FK dùng model `SupersetDataset` import từ `modules.data_dictionary.models`.
- User ID dạng chuỗi của standalone được ánh xạ sang `User.id` trong phiên Superset, import từ `modules.auth.models`. Request không được tự chọn chủ sở hữu hoặc người duyệt.
- `source_session_id` và `source_question_id` là ID tùy chọn dạng chuỗi cho đến khi module tương ứng được chuyển.
- Khi promote, module gọi schema và service sở hữu trong `glossary_management`, `metric_management`, `expert_rule_management`; không khai báo bản sao các model dùng chung.

## Model và vòng đời

- Clarification duy nhất theo `(dataset_id, user_id, idempotency_key)`. Request fingerprint cho phép retry cùng nội dung và từ chối dùng lại key với nội dung khác.
- Trạng thái clarification: `pending`, `confirmed`, `dismissed`. Người dùng chọn một đáp án gợi ý hoặc nhập định nghĩa riêng. Gửi lại câu trả lời giống hệt là idempotent; gửi nội dung khác sau khi đã trả lời sẽ bị từ chối.
- Proposal giữ loại tri thức còn thiếu, tên/khái niệm gợi ý, câu hỏi, các phương án và dataset tùy chọn. Loại phải thuộc nội dung thiếu; dataset phải trùng với clarification.
- Entry duy nhất theo `(dataset_id, user_id, kind, normalized_name)`. Cập nhật dùng `version` để phát hiện ghi đè từ màn hình cũ.
- Trạng thái review entry: `pending`, `kept_own`, `promoted`. Mở lại, cập nhật hoặc xác nhận lại sẽ xóa metadata review/promotion cũ.
- Promote tạo bản nháp thông qua service của module đích và ghi lại loại cùng UUID. Entry cá nhân chỉ tạm ngừng đưa cho agent khi bản ghi đích còn hiệu lực; nếu bản ghi chung bị xóa, thu hồi hoặc ngừng hoạt động thì tri thức cá nhân được bật lại.

## Các lớp

- `models/own_knowledge.py`: ba model clarification, proposal, entry và FK sang model Superset.
- `repositories/own_knowledge_repository.py`: truy vấn, khóa hàng, idempotency, quyền sở hữu và cập nhật theo version.
- `services/own_knowledge_service.py`: validation, xử lý câu trả lời, review, promote và kiểm tra hiệu lực; không đọc request hoặc commit.
- `dependencies.py`: nối repository/service với session của Superset.
- `routes/route_own_knowledge.py`: xác thực body, quyền Text to BI, CSRF và transaction.
- `migrations.py`: đảm bảo bảng Metric, Glossary, Expert Rule trước khi tạo ba bảng riêng của Own Knowledge, dùng advisory lock chung.

## API

Resource: `/extensions/text-to-bi/superset-text-to-bi/own-knowledge`.

| Method | Path | Mục đích |
| --- | --- | --- |
| POST | `/clarifications` | Tạo clarification idempotent cho user hiện tại và dataset được phép xem |
| GET | `/clarifications/<id>` | Xem clarification của chính user |
| POST | `/clarifications/<id>/answer` | Xác nhận hoặc bỏ qua clarification |
| GET | `/agent/entries?dataset_id=...` | Lấy tri thức cá nhân đang hoạt động của user hiện tại |
| PUT | `/agent/entries/<id>` | Sửa entry sở hữu, yêu cầu `expected_version` |
| DELETE | `/agent/entries/<id>` | Xóa entry sở hữu |
| GET | `/admin/entries` | Danh sách review Admin; lọc tùy chọn theo dataset, trạng thái, user |
| GET | `/admin/entries/<id>` | Xem entry cần review |
| POST | `/admin/entries/<id>/review` | Giữ riêng hoặc mở lại entry, yêu cầu `expected_version` |
| POST | `/admin/entries/<id>/promote` | Promote qua service module đích, yêu cầu `expected_version` |

API lấy user/reviewer từ phiên Superset. Route của user cần quyền xem Text to BI; route review/promote yêu cầu Admin. Quyền truy cập dataset của Superset vẫn được áp dụng. Request ghi cần CSRF. Các API key agent/admin riêng của standalone được thay bằng xác thực Superset và role Text to BI.

## Migration

`ensure_own_knowledge_tables()` đảm bảo các module Metric, Glossary, Expert Rule trước, rồi chỉ tạo ba bảng Own Knowledge; không tạo/sửa bảng Superset. Phiên bản extension trước đây dùng bảng `user_definitions` cho luồng cũ của AI Agent `definitions`; model đó đã được thay bằng hợp đồng Own Knowledge của standalone. Nếu môi trường đã lưu dữ liệu ở bảng cũ, cần chuyển đổi dữ liệu riêng trước khi xóa bảng; migration này không tự xóa hoặc diễn giải lại dữ liệu đó.
