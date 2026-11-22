# Data Lineage

Module `data_lineage` trong extension Text to BI cung cấp đồ thị phụ thuộc giữa các dataset Superset, cho phép quản trị viên lưu layout và người có quyền sửa dataset quản lý cạnh thủ công.

## Chủ sở hữu model

- `SupersetDataset` và `SupersetDatabase` là alias model chuẩn của Superset được export từ module `data_dictionary`; migration không tạo các bảng catalog này.
- `ColumnDictionary` thuộc `data_dictionary`; module dùng repository của module đó để suy ra cạnh từ các cặp cột tham chiếu đã khai báo.
- `LineageEdge` thuộc `data_lineage`, lưu cạnh thủ công hoặc override ẩn/màu cho cạnh suy ra. FK nguồn/đích trỏ thẳng tới ID dataset Superset.
- `LineageCanvas` thuộc `data_lineage`, lưu bố cục JSON theo database Superset.

Các bảng extension nằm trong schema `text_to_bi`: `lineage_edges` và `lineage_canvases`. Không khai báo bản sao của `TableDictionary`, `ColumnDictionary`, dataset hay database.

## Lớp module

- `repositories/`: truy vấn cạnh và canvas.
- `services/srv_data_lineage.py`: dựng graph, áp override và lưu canvas/cạnh; service không đọc Flask request và không commit.
- `dependencies.py`: tạo service/repository trên `superset.extensions.db.session`.
- `routes/route_data_lineage.py`: xác thực payload, gọi service, kiểm tra quyền, commit/rollback.
- `migrations.py`: tạo riêng hai bảng lineage, dùng schema `text_to_bi`, advisory lock và `checkfirst` để an toàn khi nhiều worker khởi động.

## API và quyền

API đăng ký tại `entrypoint.py`, resource `data-lineage`:

| Method và path | Mục đích | Quyền |
| --- | --- | --- |
| `GET /graph?database_id=<id>` | Đọc dataset người dùng được phép xem, cạnh suy ra từ dictionary và layout đã lưu | Quyền xem Text to BI cùng quyền truy cập dataset Superset |
| `PUT /canvas?database_id=<id>` | Lưu layout node/cạnh | Admin Superset |
| `POST /edges` | Thêm cạnh thủ công hoặc bỏ ẩn cạnh suy ra | Có quyền sửa cả hai dataset |
| `PUT /edges/color` | Đặt hoặc xóa màu cạnh | Có quyền sửa cả hai dataset |
| `DELETE /edges` | Ẩn cạnh suy ra hoặc xóa cạnh thủ công | Có quyền sửa cả hai dataset |

Các request ghi cần CSRF token. API dùng `ColumnDictionary.referenced_dataset_id` và `referenced_column_name`; module chưa tự tạo quan hệ dựa trên suy đoán tên cột. Cạnh loại `transform` có thể được lưu thủ công; tự suy ra transform sẽ được nối khi data dictionary sở hữu model transformation trong extension mới.

## Migration và tích hợp

Route gọi `ensure_data_dictionary_tables()` trước khi đọc quan hệ cột và `ensure_data_lineage_tables()` trước khi truy cập bảng lineage. Migration không sửa schema hoặc bảng Superset. `entrypoint.py` đăng ký `DataLineageAPI`.

Khi module khác cần cạnh lineage, import model/service/repository từ `modules.data_lineage`; không khai báo thêm model cạnh hoặc canvas trong module đó.
