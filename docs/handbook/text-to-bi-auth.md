# Module `auth` của Text to BI

Module nằm tại `extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/` và phụ trách danh tính,
quyền truy cập Text to BI, cùng các role riêng của extension. User và role nền tảng vẫn do Superset quản lý.

## User model và lưu trữ

`models/model_user.py` export trực tiếp `User` từ `flask_appbuilder.security.sqla.models`. Đây là model Superset dùng cho
bảng `ab_user`; module không định nghĩa bản sao model, không tạo bảng user khác và không sửa user. Cách dùng chung model
tránh lệch cấu trúc khi Superset thay đổi model.

Superset sở hữu vòng đời user và các bảng xác thực/role của Flask-AppBuilder. Vì thế `User` không nằm trong
`migrations.EXTENSION_MODELS`, và module auth không có migration riêng. Mọi ID user được lưu ở module khác phải tham chiếu
`ab_user.id` theo kiểu số nguyên.

## Các lớp

| Thành phần | Trách nhiệm |
| --- | --- |
| `models/model_user.py` | Export model user gốc của Flask-AppBuilder/Superset |
| `repositories/repo_user.py` | Đọc user theo ID và liệt kê user đang hoạt động qua SQLAlchemy session |
| `services/srv_user.py` | `UserService`: lấy user, yêu cầu user tồn tại, liệt kê user hoạt động và lấy tên hiển thị |
| `dependencies.py` | Tạo `UserService` với `superset.extensions.db.session` hiện hành |
| `services/srv_access.py` | Kiểm tra đăng nhập, role, permission Text to BI và quyền dataset Superset |
| `services/srv_roles.py` | Khai báo và đồng bộ các role/permission riêng của Text to BI |
| `routes/route_auth.py` | API `/me` và gán role Text to BI; không cung cấp CRUD cho user Superset |

Repository và service chỉ đọc user; transaction xác thực, thêm, sửa, khóa hoặc xóa user thuộc Superset. `require_user`
ném `UserNotFoundError` nếu ID không tồn tại. Dependency `user_service()` lấy session từ Superset để truy vấn cùng metadata
database và transaction hiện hành.

## Role và quyền

Superset tiếp tục xác thực người dùng và lưu role. Extension khai báo ba role nghiệp vụ `Text to BI Viewer`,
`Text to BI Editor`, `Text to BI Query`, cùng các permission ở view menu `Text to BI`. Role bootstrap chạy idempotent;
permission của extension được giữ admin-only khỏi các role Superset mặc định.

`/auth/me` trả user hiện tại và quyền hiệu lực. `/auth/role-assignments` chỉ cho Admin xem danh sách user hoạt động và thay
thế các role Text to BI của user; các role Superset khác của user được giữ nguyên. Route không quản lý mật khẩu hay vòng đời
user. Mọi truy cập dataset còn phải qua kiểm tra quyền dataset của Superset.
