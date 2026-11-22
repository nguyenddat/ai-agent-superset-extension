# Data Lineage

Module `data_lineage` trong extension Text to BI cung cấp đồ thị phụ thuộc giữa các dataset Superset, phép biến đổi có khai báo nguồn/cột, SQL preview và layout canvas.

## Chủ sở hữu model

- `SupersetDataset` và `SupersetDatabase` là alias model chuẩn của Superset được export từ module `data_dictionary`; migration không tạo các bảng catalog này.
- `ColumnDictionary` thuộc `data_dictionary`; module dùng repository của module đó để suy ra cạnh từ các cặp cột tham chiếu đã khai báo.
- `LineageEdge` thuộc `data_lineage`, lưu cạnh thủ công hoặc override ẩn/màu cho cạnh suy ra. FK nguồn/đích trỏ thẳng tới ID dataset Superset.
- `LineageCanvas` thuộc `data_lineage`, lưu bố cục JSON theo database Superset.
- `LineageTransformation`, `LineageTransformationInput` và `LineageColumnDependency` thuộc `data_lineage`, lưu phép biến đổi và phụ thuộc cấp cột. Cột tham chiếu bằng tên kết hợp dataset ID; không FK tới `table_columns` vì Superset có thể thay ID cột khi đồng bộ.

Các bảng extension nằm trong schema `text_to_bi`: `lineage_edges`, `lineage_canvases`, `lineage_transformations`, `lineage_transformation_inputs`, `lineage_column_dependencies`. Không khai báo bản sao của `TableDictionary`, `ColumnDictionary`, dataset hay database.

## Lớp module

- `repositories/`: truy vấn cạnh, canvas và phép biến đổi.
- `services/srv_data_lineage.py`: dựng graph, áp override, lưu canvas/cạnh, kiểm tra quyền dataset và quản lý phép biến đổi; service không đọc Flask request và không commit.
- `services/sql_preview.py`: chỉ phân tích một câu SELECT bằng SQLGlot để gợi ý nguồn và phụ thuộc cột; không chạy SQL do client gửi.
- `dependencies.py`: tạo service/repository trên `superset.extensions.db.session`.
- `routes/route_data_lineage.py`: xác thực payload, gọi service, kiểm tra quyền, commit/rollback.
- `migrations.py`: tạo năm bảng lineage (cạnh, canvas, phép biến đổi, input và phụ thuộc cột), dùng schema `text_to_bi`, advisory lock và `checkfirst` để an toàn khi nhiều worker khởi động.

## API và quyền

API đăng ký tại `entrypoint.py`, resource `data-lineage`:

| Method và path | Mục đích | Quyền |
| --- | --- | --- |
| `GET /graph?database_id=<id>` | Đọc dataset người dùng được phép xem, cạnh suy ra từ dictionary và layout đã lưu | Quyền xem Text to BI cùng quyền truy cập dataset Superset |
| `PUT /canvas?database_id=<id>` | Lưu layout node/cạnh | Admin Superset |
| `POST /edges` | Thêm cạnh thủ công hoặc bỏ ẩn cạnh suy ra | Có quyền sửa cả hai dataset |
| `PUT /edges/color` | Đặt hoặc xóa màu cạnh | Có quyền sửa cả hai dataset |
| `DELETE /edges` | Ẩn cạnh suy ra hoặc xóa cạnh thủ công | Có quyền sửa cả hai dataset |
| `GET /transformations?database_id=<id>` | Danh sách phép biến đổi và phụ thuộc cột | Quyền xem Text to BI và dataset |
| `GET /transformations/<id>?database_id=<id>` | Chi tiết một phép biến đổi | Quyền xem Text to BI và dataset |
| `POST /transformations?database_id=<id>` | Tạo phép biến đổi | Quyền sửa dataset nguồn và đích |
| `PUT /transformations/<id>?database_id=<id>` | Cập nhật phép biến đổi và thay toàn bộ nguồn/phụ thuộc | Quyền sửa dataset nguồn và đích |
| `DELETE /transformations/<id>?database_id=<id>` | Xóa phép biến đổi | Quyền sửa dataset đích |
| `POST /preview?database_id=<id>` | Phân tích SELECT, trả nguồn/phụ thuộc gợi ý và cảnh báo | Quyền xem Text to BI và dataset đích |
| `GET /datasets/<dataset_id>/view-sql?database_id=<id>` | Đọc định nghĩa view qua SQLAlchemy Inspector của Superset Database | Quyền xem Text to BI và dataset Superset |

Các request ghi cần CSRF token. API dùng `ColumnDictionary.referenced_dataset_id` và `referenced_column_name` để suy ra relation. Transformations được quản lý tường minh theo dataset; cột đầu vào/đầu ra được kiểm tra với `TableColumn` hiện tại. SQL preview chỉ parse, còn đọc view SQL dùng inspector qua engine do Superset quản lý sau khi xác thực quyền dataset; module không thực thi SQL client gửi.

## Migration và tích hợp

Route gọi `ensure_data_dictionary_tables()` trước khi đọc quan hệ cột và `ensure_data_lineage_tables()` trước khi truy cập bảng lineage. Migration không sửa schema hoặc bảng Superset. `entrypoint.py` đăng ký `DataLineageAPI`.

Khi module khác cần cạnh lineage, import model/service/repository từ `modules.data_lineage`; không khai báo thêm model cạnh hoặc canvas trong module đó.
