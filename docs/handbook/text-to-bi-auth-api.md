# Auth API của Text to BI

Base resource: `/extensions/text-to-bi/superset-text-to-bi/auth`.

Nguồn: [routes](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/routes/route_auth.py),
[schemas](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/schemas/schema_auth.py),
[role](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/services/srv_roles.py).

API dùng phiên đăng nhập và bảng bảo mật của Superset (`ab_user`, `ab_role`, `ab_user_role`...). API không tạo, sửa,
khóa hay xóa user hoặc role Superset; quản trị chung vẫn qua màn hình và API của Superset. Cách role và permission được
seed xem [module auth](text-to-bi-auth.md).

## Endpoint

| Method | Path | Quyền | Response 200 |
| --- | --- | --- | --- |
| GET | `/me` | Đăng nhập, `can_read` | `{user_id, username, name, is_admin, can_view, can_edit, can_query, can_review}` |
| GET | `/role-assignments` | Admin | `{roles: [{name, description}], users: [RoleAssignment]}` |
| PUT | `/role-assignments/<user_id>` | Admin, CSRF | `RoleAssignment` |
| GET | `/users/<user_id>/roles` | Admin | `UserRoles` |
| PUT | `/users/<user_id>/roles` | Admin, CSRF | `UserRoles` |
| POST | `/users/<user_id>/roles/<role_id>` | Admin, CSRF | `UserRoles` |
| DELETE | `/users/<user_id>/roles/<role_id>` | Admin, CSRF | `UserRoles` |

- `RoleAssignment`: `{user_id, username, name, is_admin, roles, other_roles}`; `roles` là các role Text to BI của user,
  `other_roles` là mọi role khác. `GET /role-assignments` liệt kê mọi user đang hoạt động.
- `UserRoles`: `{user_id, username, role_ids, roles}`, sắp theo tên role.
- `/me` trả cờ quyền đã tính cả Admin (Admin có mọi cờ `can_*`). Frontend gọi nó khi tải trang để dựng menu; mục Tri
  thức riêng gọi `GET /role-assignments` để hiển thị tên user.

## Payload

`PUT /role-assignments/<user_id>`:

```json
{"roles": ["Text to BI Viewer", "Text to BI Query"]}
```

Tối đa 10 tên, mỗi tên phải là một trong bốn role Text to BI; tên trùng bị bỏ. Lệnh chỉ thay nhóm role Text to BI,
giữ nguyên mọi role khác của user.

`PUT /users/<user_id>/roles`:

```json
{"role_ids": [3, 8]}
```

Tối đa 100 ID; ID trùng bị bỏ; một ID không tồn tại làm cả request thất bại. Lệnh thay toàn bộ role Superset của user,
kể cả role ngoài Text to BI, nên client phải gửi mọi role muốn giữ. `POST` và `DELETE` chỉ thêm hoặc gỡ một liên kết
user-role, không xóa role.

## Bảo mật và lỗi

Mọi route có `@protect()` của Flask-AppBuilder: cần phiên Superset và permission `can_read` (GET) hoặc `can_write`
(ghi) trên `text_to_bi_api`. Route ghi kiểm tra header `X-CSRFToken`. Các route ngoài `/me` còn yêu cầu role `Admin`.
Mọi route gọi `ensure_auth_roles()` trước khi đọc hoặc ghi, riêng `/me` chỉ gọi khi user có ít nhất một quyền.

| Status | `code` | Khi nào |
| --- | --- | --- |
| 401 | `sign_in_required` | Chưa đăng nhập |
| 403 | `admin_required` | Người gọi không phải Admin |
| 403 | `csrf_token_invalid` | Thiếu hoặc sai CSRF token |
| 404 | `user_not_found` | `user_id` không tồn tại |
| 404 | `role_not_found` | Role Text to BI chưa có trong Superset khi gán theo tên |
| 422 | `invalid_role_assignment` | Tên role ngoài bốn role Text to BI, hoặc `role_id` không tồn tại |
| 422 | `invalid_request` | Body sai schema hoặc có field lạ |
| 500 | `internal_error` | Lỗi không dự kiến; transaction được rollback |

Lỗi validation không trả lại chi tiết input. Flask-AppBuilder tự trả 401/403 dạng `{msg}` khi `@protect()` từ chối.
