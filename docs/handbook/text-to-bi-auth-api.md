# Auth API của Text to BI

Trang này mô tả API do extension cung cấp tại resource `auth`. API dùng phiên đăng nhập và các bảng bảo mật có sẵn của Superset; module không tạo bảng user, role hay association riêng.

Nguồn triển khai: [routes](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/routes/route_auth.py), [schemas](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/schemas/schema_auth.py), [role permissions](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/auth/services/srv_roles.py).

## API native Superset và API extension

Superset sở hữu user (`ab_user`), role (`ab_role`), permission (`ab_permission`, `ab_view_menu`, `ab_permission_view`) và các association user-role/role-permission. Model trong `modules/auth.models` chỉ import alias model Flask-AppBuilder của Superset. Module auth không thay thế API native Superset dùng để quản trị user hoặc role chung.

Các endpoint `/auth/...` dưới đây là API extension. Chúng seed bốn role Text to BI vào bảng role có sẵn và gán quyền vào permission view `Text to BI`; các thao tác user-role ghi thẳng association `ab_user_role` thông qua Superset security manager. Endpoint gán nhóm role chung nhận ID role Superset, không tạo role mới thay thế hệ thống phân quyền Superset.

API native Superset để quản trị user, role và dataset vẫn được phục vụ bởi Superset; extension không chuyển tiếp hay thay thế các endpoint đó. Các endpoint trong bảng tiếp theo chỉ quản lý role assignment theo nhu cầu Text to BI.

Base resource: `/extensions/text-to-bi/superset-text-to-bi/auth`.

## Role và quyền

| Role Text to BI | Quyền extension |
| --- | --- |
| `Text to BI Viewer` | Xem API và metadata dataset mà user có quyền đọc trong Superset |
| `Text to BI Editor` | Quyền Viewer và sửa metadata trên dataset user được phép truy cập |
| `Text to BI Steward` | Quyền xem, sửa và review semantic metadata theo permission `can_review` |
| `Text to BI Query` | Gọi khả năng query trên dataset user có quyền đọc |
| `Admin` | Quyền quản trị; được xem/sửa mọi dataset theo permission Superset tương ứng |

Permission route-level `can_read`/`can_write` chỉ mở API class. Service/route tiếp tục kiểm tra quyền Text to BI và quyền dataset Superset; quyền `Admin` không bỏ qua ACL dataset. Một số thao tác review trong các module nghiệp vụ có thể giới hạn Admin riêng.

## Endpoint

| Method | Path | Mục đích và quyền |
| --- | --- | --- |
| GET | `/me` | Trả user hiện tại và cờ `is_admin`, `can_view`, `can_edit`, `can_query`, `can_review`; cần đăng nhập và permission đọc API |
| GET | `/role-assignments` | Trả danh sách role Text to BI và user Superset đang hoạt động cùng role hiện tại; chỉ Admin |
| PUT | `/role-assignments/<user_id>` | Thay các role Text to BI của user theo tên; chỉ Admin |
| GET | `/users/<user_id>/roles` | Đọc toàn bộ role Superset đang gán cho user; chỉ Admin |
| PUT | `/users/<user_id>/roles` | Thay toàn bộ role của user bằng danh sách `role_ids`; chỉ Admin |
| POST | `/users/<user_id>/roles/<role_id>` | Gán thêm role Superset cho user; chỉ Admin |
| DELETE | `/users/<user_id>/roles/<role_id>` | Gỡ role Superset khỏi user; chỉ Admin |

### Payload và response chính

`PUT /role-assignments/<user_id>` nhận:

```json
{"roles": ["Text to BI Viewer", "Text to BI Query"]}
```

Tên role phải nằm trong bốn role Text to BI; danh sách tối đa 10 phần tử. Thay nhóm Text to BI giữ lại các role khác của user, gồm role Superset hiện có.

`PUT /users/<user_id>/roles` nhận:

```json
{"role_ids": [3, 8]}
```

`role_ids` tối đa 100 phần tử. ID không tồn tại làm request thất bại; danh sách trùng được loại bỏ. Đây là thay toàn bộ danh sách role của user, nên client cần gửi mọi role muốn giữ lại. `POST`/`DELETE` thay đổi từng association và không xóa role khỏi Superset.

Response role assignment gồm `user_id`, `username`, `name`, `is_admin`, `roles`, `other_roles`. Response CRUD role chung gồm `user_id`, `username`, `role_ids`, `roles`. `/me` trả các trường quyền cùng `user_id`, `username`, `name`.

## Bảo mật, CSRF và lỗi

Tất cả endpoint yêu cầu phiên Superset hợp lệ qua Flask-AppBuilder `@protect`. Thao tác ghi (`PUT`, `POST`, `DELETE`) cần CSRF token theo cơ chế Superset; gửi cookie phiên cùng header `X-CSRFToken`. Các endpoint gán role yêu cầu người gọi thuộc role `Admin`, kể cả khi người đó có quyền ghi API class.

Các lỗi module trả JSON `{ "code", "message" }`: chưa đăng nhập `401`; không đủ quyền `403`; user hoặc role không tồn tại `404`; role/body không hợp lệ `422`; lỗi không dự kiến `500`. Body Pydantic cấm field ngoài schema; lỗi validation không trả chi tiết input lên client.

Role Text to BI được tạo idempotent khi module bootstrap. Module dùng bảng Superset sẵn có; không có migration tạo bảng.
