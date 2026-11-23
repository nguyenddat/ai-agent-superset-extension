# Module `auth` của Text to BI

Module nằm tại `extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/`. Module cho biết user
hiện tại được làm gì trong Text to BI, seed các role của extension vào bảng bảo mật Superset, kiểm tra quyền cho mọi
module khác và phục vụ trang `/text-to-bi/`. Superset vẫn quản lý user, role, permission và phiên đăng nhập.

## Dữ liệu

`models/model_user.py` và `models/model_role.py` chỉ export model Flask-AppBuilder của Superset: `User`, `Role`,
`Permission`, `PermissionView`, `ViewMenu` và các association table. Chúng ánh xạ tới `ab_user`, `ab_role`,
`ab_permission`, `ab_permission_view`, `ab_view_menu`, `ab_user_role` và `ab_permission_view_role`. Module không có bảng
riêng.

`migrations.py` cung cấp `ensure_auth_roles()`: chạy một lần mỗi process, dưới PostgreSQL advisory lock, seed role và
permission vào bảng Superset có sẵn, không chạy DDL. Hàm được gọi ở `/auth/me` (lần đầu một user có quyền nào đó gọi)
và ở mọi route quản trị role.

## Các lớp

| Thành phần | Trách nhiệm |
| --- | --- |
| `models/` | Export model bảo mật của Superset |
| `repositories/` | Đọc user (theo ID, user đang hoạt động) và role (theo ID, tên, toàn bộ) |
| `services/srv_user.py` | `UserService`: tra cứu user, tên hiển thị |
| `services/srv_roles.py` | Định nghĩa bốn role, seed role, gán role cho user |
| `services/srv_access.py` | Các hàm `can_*` và `require_*` mà mọi module dùng |
| `routes/route_auth.py` | `AuthAPI`, resource `auth`; xem [Auth API](text-to-bi-auth-api.md) |
| `routes/route_page.py` | `TextToBIView`: trang Superset `/text-to-bi/` mà frontend gắn vào |
| `dependencies.py` | Tạo `RoleService`, `UserService` trên `superset.extensions.db.session` |

## Role và permission

Permission của extension nằm trên view menu `Text to BI`; mọi API class dùng chung class permission `text_to_bi_api`
(`can_read` cho GET, `can_write` cho thao tác ghi).

| Role | Permission |
| --- | --- |
| `Text to BI Viewer` | `can_view`, `can_read` API |
| `Text to BI Editor` | `can_view`, `can_edit`, `can_read` và `can_write` API |
| `Text to BI Steward` | `can_view`, `can_edit`, `can_review`, `can_read` và `can_write` API |
| `Text to BI Query` | `can_query`, `can_read` và `can_write` API |

`ensure_text_to_bi_roles()` tạo bốn role trên, cấp thêm `can_view`, `can_edit`, `can_review`, `can_query` cho `Admin`
và thu hồi bốn permission đó khỏi `Alpha`, `Gamma`, `Public`, `sql_lab`. Khi extension nạp, `entrypoint.py` gọi
`declare_text_to_bi_admin_only()` để đưa `Text to BI` và `text_to_bi_api` vào `ADMIN_ONLY_VIEW_MENUS`, nên bước đồng
bộ role của Superset không cấp các permission này cho role mặc định.

## Kiểm tra quyền

- `is_admin()` đúng khi user có role `Admin`; Admin qua mọi kiểm tra `can_*` của extension.
- `can_view()`, `can_edit_datasets()`, `can_query_datasets()`, `can_review_semantic_layer()` kiểm tra permission tương
  ứng trên view menu `Text to BI`.
- `require_view`, `require_review`, `require_admin` chỉ kiểm tra quyền extension. `require_edit(dataset)` và
  `require_query(dataset)` kiểm tra quyền extension rồi tới ACL dataset của Superset
  (`security_manager.raise_for_access`). ACL dataset áp dụng cả với Admin.
- Lỗi trả JSON `{code, message}`: `sign_in_required` (401), `admin_required`, `view_permission_required`,
  `edit_permission_required`, `review_permission_required`, `query_permission_required`, `dataset_access_required`
  (403), `invalid_role_assignment` (422).

## Giao diện

Frontend gọi `GET /auth/me` một lần khi tải trang (`lib/access.ts`) và dùng kết quả để quyết định menu và mục được mở
(`canOpenSection` trong `features/workspace/workspace-layout.tsx`):

| Menu trên navbar Superset | Mục (`?section=`) | Điều kiện |
| --- | --- | --- |
| AI Agent | Hỏi dữ liệu (`chat`) | `can_query` |
| AI Agent | Tri thức riêng (`own-knowledge`) | `is_admin` |
| Mô hình dữ liệu | Từ điển (`dictionary`), Mô hình (`model`), Dòng dữ liệu (`lineage`) | `can_view` |
| Quản trị dữ liệu | Tổng quan (không có `section`), Metric (`metrics`), Thuật ngữ (`glossary`), Quy tắc (`rules`) | `can_view` |

User không mở được mục nào thì không thấy menu. Mục lạ hoặc không được phép trên URL được thay bằng Tổng quan, hay bằng
mục đầu tiên user mở được nếu user không xem được Tổng quan (ví dụ user chỉ có quyền Query sẽ vào Hỏi dữ liệu).
Trang `/text-to-bi/` chuyển user chưa đăng nhập tới trang login và trả 403 khi user không có `can_view` lẫn
`can_query`. Extension chưa có màn hình gán role; Admin dùng màn hình quản lý user của Superset hoặc Auth API.

## Kiểm thử

Mọi test trong `backend/tests/test_auth.py` hiện lỗi ở bước dựng fixture vì `tests/conftest.py` chưa có bản giả cho
`superset.connectors` và `superset.models.core`.
