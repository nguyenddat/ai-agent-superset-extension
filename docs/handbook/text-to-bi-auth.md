# Module `auth` của Text to BI

Module nằm tại `extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/`, quản lý danh tính hiện tại, quyền truy cập Text to BI và các role của extension. Superset tiếp tục quản lý user, role, permission và các bảng liên quan.

## Model và migration

`models/model_user.py` và `models/model_role.py` export các model Flask-AppBuilder của Superset: `User`, `Role`, `Permission`, `PermissionView`, `ViewMenu` và association tables. Chúng ánh xạ tới `ab_user`, `ab_role`, `ab_permission`, `ab_permission_view`, `ab_view_menu`, `ab_user_role` và `ab_permission_view_role`. Module không định nghĩa hay tạo bảng auth riêng.

`modules/auth/migrations.py` là migration nội bộ của auth: `ensure_auth_roles()` idempotent, seed các role/permission Text to BI vào bảng Superset hiện có. Không chạy DDL. Migration tổng thể `migrations.py` chỉ quản lý bảng dữ liệu extension và không seed role.

## Các lớp

| Thành phần | Trách nhiệm |
| --- | --- |
| `models/` | Export model Superset |
| `repositories/` | Truy vấn user và role bằng SQLAlchemy session |
| `services/srv_user.py`, `services/srv_roles.py` | Tra cứu user/role, seed role và gán role |
| `services/srv_access.py` | Kiểm tra đăng nhập, quyền Text to BI và quyền dataset Superset |
| `routes/route_auth.py` | `/me`, gán role Text to BI và CRUD liên kết user-role |
| `dependencies.py` | Cung cấp service dùng `superset.extensions.db.session` |

Auth API không tạo, sửa hồ sơ, khóa hay xóa user Superset. `require_user` báo lỗi nếu user ID không tồn tại.

## Role và quyền

Extension khai báo `Text to BI Viewer`, `Text to BI Editor`, `Text to BI Steward` và `Text to BI Query`, cùng permission trên view menu `Text to BI`. Steward có quyền sửa và `can_review` để duyệt, thu hồi hoặc xóa nội dung đã duyệt. Quyền dataset vẫn do Superset kiểm tra. Permission riêng của extension được giữ admin-only, không cấp cho các role Superset mặc định.

Superset dùng RBAC: permission được gán cho role, user nhận quyền thông qua role. Auth API vì vậy chỉ quản lý liên kết `ab_user_role`, không gán permission trực tiếp cho user. Các route `/auth/users/<user_id>/roles` hỗ trợ GET (xem danh sách), PUT (thay thế toàn bộ role IDs); `/auth/users/<user_id>/roles/<role_id>` hỗ trợ POST (gán) và DELETE (thu hồi). Chỉ Superset Admin được gọi. Đây là thao tác toàn bộ role Superset; PUT thay thế cả role ngoài Text to BI.

`/auth/role-assignments` tiếp tục là giao diện hẹp cho Admin quản lý các role Text to BI và giữ nguyên các role Superset khác của user. `/auth/me` trả user hiện tại cùng quyền hiệu lực.
