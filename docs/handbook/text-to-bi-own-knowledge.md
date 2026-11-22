# Own Knowledge

`own_knowledge` lưu những cách hiểu nghiệp vụ do từng người dùng xác nhận trong ngữ cảnh một dashboard. Đây là bản chuyển đổi từ module `definitions` của AI Agent standalone. Mỗi bản ghi chỉ thuộc người dùng lấy từ phiên Superset; API không nhận `user_id` từ client.

## Model và quyền sở hữu

- `UserDefinition` là model của module này, bảng `text_to_bi.user_definitions`.
- `user_id` và `reviewed_by` tham chiếu model `User` import từ `modules.auth.models` (bảng Superset `ab_user`).
- `dashboard_id` tham chiếu `dashboards.id` do Superset quản lý. Service yêu cầu Superset kiểm tra quyền truy cập dashboard trước khi liệt kê hoặc lưu định nghĩa.
- `source_question_id` và `source_session_id` là ID tùy chọn. Chúng chưa có FK vì module question/conversation chưa được chuyển; khi các module đó có model owner, cần import model đầy đủ và bổ sung FK.
- `kind` nhận `glossary` hoặc `expert_rule`. Định nghĩa cá nhân là tín hiệu từ người dùng; nó không tự tạo hoặc duyệt thuật ngữ chung hay quy tắc chuyên gia.
- `review_status` nhận `pending`, `promoted` hoặc `ignored`. Nội dung được sửa hoặc xác nhận lại sẽ quay về `pending`.

## Lớp module

- `models/user_definition.py`: model và ràng buộc tên trong phạm vi user/dashboard/loại.
- `repositories/repo_user_definition.py`: truy vấn theo chủ sở hữu, dashboard và danh sách review.
- `services/own_knowledge_service.py`: kiểm tra nội dung, dashboard access, lưu và review; không đọc request hoặc commit transaction.
- `dependencies.py`: tạo service/repository trên `superset.extensions.db.session`.
- `routes/route_own_knowledge.py`: xác thực body, quyền, CSRF và transaction.
- `migrations.py`: tạo riêng bảng của module trong schema `text_to_bi`, dùng advisory lock và `checkfirst`; không tạo bảng Superset.

## API

Resource: `/extensions/text-to-bi/superset-text-to-bi/own-knowledge`.

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/` với `dashboard_id` | Liệt kê định nghĩa của user đăng nhập; yêu cầu quyền xem Text to BI và quyền truy cập dashboard Superset |
| PUT | `/<definition_id>` | Sửa định nghĩa của chính user; trạng thái review trở về `pending` |
| DELETE | `/<definition_id>` | Xóa định nghĩa của chính user |
| GET | `/review` | Liệt kê định nghĩa cho Admin review |
| PUT | `/review` | Đặt trạng thái nhiều định nghĩa thành `pending`, `promoted` hoặc `ignored`; chỉ Admin |

Ghi dữ liệu cần CSRF. Tất cả endpoint cá nhân lọc bằng `current_user_id()`; ID không thuộc người gọi được trả về như không tìm thấy. Module cung cấp `OwnKnowledgeService.save_confirmed()` để conversation/session gọi khi tích hợp; caller cần truyền user ID lấy từ phiên đăng nhập và dữ liệu xác nhận đã được validate.

## Migration và tích hợp

`ensure_own_knowledge_tables()` chỉ tạo bảng `user_definitions`. Route gọi migration trước truy vấn. Khi chuyển conversation/session, cần gọi service `save_confirmed()` sau khi xác nhận định nghĩa; nếu muốn dựng lại thông tin review gồm người hỏi và tiêu đề dashboard, hãy import model/repository owner của các module đó thay vì khai báo lại model ở đây.
