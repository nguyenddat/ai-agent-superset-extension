# API tích hợp Superset

`modules/superset` là lớp adapter nội bộ cho metadata và quyền Superset. Module không đăng ký route Text to BI, không sao chép model database, dataset, column, metric, user hay role. Các API REST native của Superset tiếp tục quản lý những tài nguyên đó; backend extension gọi DAO và security manager của Superset.

## Hợp đồng service nội bộ

| Service | Hàm | Hành vi |
| --- | --- | --- |
| `services/srv_dataset.py` | `get_dataset`, `require_dataset`, `get_datasets`, `datasets_on_database`, `get_database` | Đọc `SqlaTable` và `Database` qua DAO Superset. `require_dataset` báo lỗi không tìm thấy nếu DAO không trả dataset mà caller được phép thấy. |
| `services/srv_dataset.py` | `can_access_dataset`, `readable_datasets` | Kiểm tra ACL datasource bằng `security_manager.raise_for_access`. Catalog đọc được cũng loại database được đánh dấu nội bộ cho Text to BI. |
| `services/srv_dataset.py` | `dataset_columns`, `column_type`, `dataset_kind`, `database_name` | Chuẩn hóa metadata từ model dataset/column Superset cho các module nghiệp vụ. |
| `services/srv_user.py` | `get_user`, `require_user`, `active_users`, `user_display_name` | Ủy quyền truy vấn user cho `modules/auth`; danh tính và lưu trữ user vẫn thuộc Superset. |
| `services/srv_role.py` | `ensure_role`, `require_role`, `replace_user_roles`, `revoke_permissions`, `declare_admin_only_view_menu` | Dùng security manager và association role/permission của FAB. Module Auth sở hữu việc seed role Text to BI và các route gán quyền. |

Module khác gọi các helper này hoặc import alias model Superset chính thức từ model owner `data_dictionary` và `auth`. Không khai báo model trùng và không tạo bảng do Superset sở hữu trong migration của extension.

## Ranh giới truy vấn và quyền

- Truy vấn dataset đi qua helper chung và áp dụng ACL Superset của caller. `datasets_on_database` dùng DAO dataset có lọc quyền; dùng `readable_datasets` khi cần toàn bộ catalog nghiệp vụ mà caller được phép đọc.
- `is_internal_dataset` nhận diện database báo cáo riêng của Text to BI bằng cờ `text_to_bi_internal` trong `Database.extra`; cờ này không chuyển quyền sở hữu database hoặc dataset khỏi Superset.
- `modules/superset` không tự cấp quyền. Module nghiệp vụ kết hợp `can_view`, `can_edit`, `can_query` hoặc `can_review` của Auth với ACL dataset Superset.
- Text2SQL thực thi truy vấn qua SQL Lab của Superset; xem [Text2SQL API](text-to-bi-text2sql-api.md).

## Routes

`modules/superset` không có HTTP route riêng của extension. Dùng API native Superset để quản lý database, dataset, column và user. Hợp đồng API riêng của Text to BI được ghi ở trang module sở hữu, gồm [Auth](text-to-bi-auth-api.md) và [Data Dictionary](text-to-bi-data-dictionary-api.md).
