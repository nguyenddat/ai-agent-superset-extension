# API tích hợp Superset

`modules/superset` là lớp adapter nội bộ giữa các module nghiệp vụ và Superset. Module không đăng ký route HTTP, không
có bảng hay migration, và không sao chép model database, dataset, cột, metric, user hay role. Superset vẫn quản lý các
tài nguyên đó qua màn hình và API native của nó; extension đọc chúng qua DAO và security manager của Superset.

## Hợp đồng nội bộ

| Tệp | Hàm | Hành vi |
| --- | --- | --- |
| `services/srv_dataset.py` | `get_dataset`, `require_dataset` | Đọc `SqlaTable` qua `DatasetDAO`, có bộ lọc datasource của Superset; dataset người gọi không thấy coi như không tồn tại, `require_dataset` khi đó báo `dataset_not_found` (404) |
| `services/srv_dataset.py` | `get_datasets`, `datasets_on_database` | Lọc kết quả `DatasetDAO.find_all()` theo danh sách ID hoặc theo `database_id`; `datasets_on_database` sắp theo database, schema, tên bảng |
| `services/srv_dataset.py` | `get_database` | Đọc `Database` qua `DatabaseDAO` |
| `services/srv_dataset.py` | `can_access_dataset`, `readable_datasets` | Kiểm tra ACL datasource bằng `security_manager.raise_for_access`; `readable_datasets` trả mọi dataset người gọi truy cập được, trừ dataset của database nội bộ |
| `services/srv_dataset.py` | `is_internal_dataset` | Database có `"text_to_bi_internal": true` trong `Database.extra` chứa view báo cáo của extension, không phải dữ liệu nghiệp vụ |
| `services/srv_dataset.py` | `dataset_columns`, `column_type`, `dataset_kind`, `database_name`, `dataset_sort_key` | Chuẩn hóa metadata dataset và cột; `dataset_kind` là `virtual` khi dataset có SQL, còn lại `physical` |
| `services/srv_user.py` | `get_user`, `require_user`, `active_users`, `user_display_name` | Ủy quyền cho `UserService` của module auth; `require_user` báo `user_not_found` (404) |
| `services/srv_role.py` | `ensure_role`, `require_role`, `replace_user_roles`, `revoke_permissions`, `declare_admin_only_view_menu` | Bọc security manager của Flask-AppBuilder; `require_role` báo `role_not_found` (404). Module auth dùng chúng để seed và gán role Text to BI |
| `dependencies.py` | `requires_dataset` | Decorator route: lấy `dataset_id` trên URL, gọi `require_dataset` và truyền `dataset` vào hàm route |
| `exceptions.py` | `DatasetNotFoundError`, `UserNotFoundError`, `RoleNotFoundError` | Lỗi 404 dùng chung |

Alias model Superset (`SupersetDatabase`, `SupersetDataset`, `SupersetDatasetColumn`, `SupersetMetric`) nằm ở
`modules/data_dictionary/models`; alias model bảo mật (`User`, `Role`...) nằm ở `modules/auth/models`. Module khác
import từ hai nơi đó, không khai báo model trùng và không tạo bảng của Superset.

## Ranh giới truy vấn và quyền

- Kết quả DAO đã qua bộ lọc datasource của Superset; module nghiệp vụ vẫn gọi `can_access_dataset` hoặc các hàm
  `require_*` của auth trước khi trả dữ liệu. Ví dụ: `GET /data-lineage/graph` và `GET /business-model/databases/<id>`
  lấy `datasets_on_database` rồi lọc bằng `can_access_dataset`; hội thoại kiểm tra `require_query` trên mọi dataset của
  database khi một lượt có hàng mà không gắn dataset.
- `modules/superset` không tự cấp quyền. Module nghiệp vụ kết hợp `can_view`, `can_edit`, `can_query`, `can_review`
  của auth với ACL dataset Superset; xem [module auth](text-to-bi-auth.md).
- Text2SQL chạy truy vấn qua lớp thực thi SQL Lab của Superset (`modules/text2sql/services/superset_query.py`); xem
  [Text2SQL API](text-to-bi-text2sql-api.md).

## Routes

Module không có route riêng. Trang `/text-to-bi/` là `TextToBIView` của module auth. API của extension được ghi ở
trang module sở hữu: [Auth](text-to-bi-auth-api.md), [Data Dictionary](text-to-bi-data-dictionary-api.md),
[Business Model](text-to-bi-business-model-api.md), [Data Lineage](text-to-bi-data-lineage-api.md),
[Conversation](text-to-bi-conversation-api.md).

## Kiểm thử

`superset.connectors` và `superset.models.core` không có bản giả trong `backend/tests/conftest.py`, nên các test nạp
alias model Superset hiện lỗi: `test_data_dictionary_api.py`, `test_data_dictionary_autofill.py` và `test_migrations.py`
lỗi ngay khi pytest nạp test, còn mọi test trong `test_auth.py` lỗi ở bước dựng fixture.
