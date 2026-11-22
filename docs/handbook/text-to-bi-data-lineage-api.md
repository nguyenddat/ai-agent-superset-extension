# Data Lineage API

Các route dưới đây thuộc resource `data-lineage` của Text to BI. URL đầy đủ có tiền tố `/api/v1/extensions/text-to-bi/superset-text-to-bi/data-lineage` (Superset API prefix có thể được cấu hình theo môi trường). Request ghi cần phiên đăng nhập, quyền `write` của resource và CSRF token; route còn áp dụng quyền xem/sửa dataset Superset hoặc quyền Admin như ghi ở bảng.

| Method và path | Quyền bổ sung | Request và kết quả |
| --- | --- | --- |
| `GET /graph?database_id=<id>` | `require_view`; quyền đọc từng dataset | Trả `{database_id, datasets, edges, canvas}`. Trả các dataset người gọi được xem, edges suy ra từ tham chiếu Data Dictionary và phép biến đổi, cạnh thủ công/ẩn/màu cùng layout đã lưu. Mỗi edge có source, target, kind, origin, label, color và columns. |
| `GET /transformations?database_id=<id>` | `require_view`; chỉ lộ dataset người gọi được xem | Trả `transformations`; mỗi mục có `id`, `target_dataset_id`, `name`, `description`, `sql_text`, `origin`, `source_dataset_ids`, `dependencies` và thời điểm audit. Mỗi dependency có `source_dataset_id`, `source_column_name`, `target_column_name`, `role`. |
| `GET /transformations/<uuid>?database_id=<id>` | `require_view`; phải xem được dataset đích và mọi nguồn | Trả `{transformation}`; UUID sai là lỗi validation, bản ghi hoặc nguồn ngoài phạm vi trả 404. |
| `POST /transformations?database_id=<id>` | Quyền sửa dataset đích và mọi nguồn | Body theo `TransformationIn`; tạo phép biến đổi, trả `{transformation}` với 201. |
| `PUT /transformations/<uuid>?database_id=<id>` | Quyền sửa dataset đích và mọi nguồn | Cùng body như POST; thay toàn bộ tập nguồn và dependency, trả `{transformation}`. |
| `DELETE /transformations/<uuid>?database_id=<id>` | Quyền sửa dataset đích | Xóa phép biến đổi; trả thông báo xác nhận. |
| `POST /preview?database_id=<id>` | `require_view`; quyền đọc dataset đích | Body `{target_dataset_id, sql_text}`; trả `target_dataset_id`, `source_dataset_ids`, `dependencies`, `warnings` và `complete` (đây chỉ là gợi ý). SQL được phân tích, không thực thi. |
| `GET /datasets/<dataset_id>/view-sql?database_id=<id>` | `require_view`; quyền truy cập dataset | Đọc SQL định nghĩa view từ Superset Database Inspector; dataset phải thuộc database đã nêu. |
| `PUT /canvas?database_id=<id>` | Chỉ Admin Superset | Body `{nodes, edges}`; lưu layout; trả `{database_id}`. Tối đa 5.000 node/cạnh, tọa độ hữu hạn trong ±100.000. |
| `POST /edges` | Quyền sửa cả hai dataset | Body `{source, target, kind}`; tạo cạnh thủ công hoặc hiện lại cạnh suy ra. Hai ID phải là dataset dương, khác nhau và cùng database; `kind` là `flow`, `relation` hoặc `transform`. |
| `PUT /edges/color` | Quyền sửa cả hai dataset | Body `{source, target, kind, color}`; `color` là mã hex hoặc `null` để bỏ màu. |
| `DELETE /edges` | Quyền sửa cả hai dataset | Body `{source, target, kind}`; ẩn cạnh suy ra hoặc xóa cạnh thủ công. |

`TransformationIn` nhận `target_dataset_id`, `name`, tùy chọn `description`/`sql_text`, `origin` (`manual`, `sql_job`, `view_sql`), `source_dataset_ids` (1–500) và `dependencies` (tối đa 5.000). Mỗi dependency gồm `source_dataset_id`, `source_column_name`, `target_column_name` tùy chọn và `role` (`value`, `group`, `join`, `filter`). Service kiểm tra dataset cùng database, quyền sửa, tên/cột hiện có, nguồn không trùng hoặc không đồng nhất với đích, và yêu cầu cột đích cho role `value`.

Các thao tác đọc catalog dùng model/API Superset hiện có qua module `superset` và Data Dictionary; module không sao chép bảng dataset/database. Đọc SQL view dùng engine của Superset Database sau kiểm tra quyền. Preview dùng SQLGlot để suy luận dependency, không gửi SQL tới database.
