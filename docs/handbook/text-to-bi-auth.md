# Module `auth` của Text to BI

Module nằm tại `extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/` và phụ trách danh tính,
quyền truy cập Text to BI, cùng các role riêng của extension. User và role nền tảng vẫn do Superset quản lý.

## User model và lưu trữ

`models/model_user.py` export trực tiếp `User` từ `flask_appbuilder.security.sqla.models`; `models/model_role.py` export
các model `Role`, `Permission`, `PermissionView`, `ViewMenu` từ cùng package. Đây là các model Superset dùng cho
`ab_user`, `ab_role`, `ab_permission`, `ab_permission_view` và `ab_view_menu`. Module không định nghĩa bản sao model,
không tạo bảng user/role/quyền khác và không thêm model Superset vào danh sách migration của extension.

Superset sở hữu vòng đời user, role và permission. Các bảng nối `ab_user_role` và `ab_permission_view_role` cũng do
Flask-AppBuilder quản lý. Vì thế các model này không nằm trong `migrations.EXTENSION_MODELS`; module auth không có
migration riêng. Mọi ID user được lưu ở module khác phải tham chiếu `ab_user.id` theo kiểu số nguyên.

## Các lớp

| Thành phần | Trách nhiệm |
| --- | --- |
| `models/model_user.py`, `models/model_role.py` | Export các model user, role, permission và view menu gốc |
| `repositories/repo_user.py`, `repositories/repo_role.py` | Đọc user và role qua SQLAlchemy session |
| `services/srv_user.py`, `services/srv_roles.py` | `UserService`, `RoleService`: tra cứu, bootstrap role/permission và gán role |
| `dependencies.py` | Tạo service với `superset.extensions.db.session` hiện hành |
| `services/srv_access.py` | Kiểm tra đăng nhập, role, permission Text to BI và quyền dataset Superset |
| `services/srv_roles.py` | Khai báo và đồng bộ các role/permission riêng của Text to BI |
| `routes/route_auth.py` | API `/me` và gán role Text to BI; không cung cấp CRUD cho user Superset |

Repository và service chỉ đọc user; transaction xác thực, thêm, sửa, khóa hoặc xóa user thuộc Superset. `require_user`
ném `UserNotFoundError` nếu ID không tồn tại. Dependency `user_service()` lấy session từ Superset để truy vấn cùng metadata
database và transaction hiện hành.

## Role và quyền

Superset tiếp tục xác thực người dùng và lưu role. Extension khai báo `Text to BI Viewer`, `Text to BI Editor`,
`Text to BI Steward` và `Text to BI Query`, cùng permission trên view menu `Text to BI`. `Steward` có quyền sửa và
permission `can_review` để duyệt/thu hồi, xóa nội dung đã duyệt. Mọi thao tác trên dataset vẫn kiểm tra quyền dataset
Superset. Role bootstrap chạy idempotent; permission của extension được giữ admin-only khỏi các role Superset mặc định.

`/auth/me` trả user hiện tại và quyền hiệu lực. `/auth/role-assignments` chỉ cho Admin xem danh sách user hoạt động và thay
thế các role Text to BI của user; các role Superset khác của user được giữ nguyên. Route không quản lý mật khẩu hay vòng đời
user. Mọi truy cập dataset còn phải qua kiểm tra quyền dataset của Superset.
