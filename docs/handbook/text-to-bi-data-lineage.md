# Data Lineage

Module `data_lineage` (`extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_lineage/`) mô tả
bảng nào tạo ra bảng nào trong một database Superset, đến từng cột: đồ thị phụ thuộc giữa dataset, phép biến đổi khai
báo nguồn và cột, phân tích SQL để gợi ý nguồn, và layout canvas. Endpoint xem
[Data Lineage API](text-to-bi-data-lineage-api.md).

## Dữ liệu

Bảng trong schema `text_to_bi`, mọi cột dataset tham chiếu thẳng ID dataset Superset:

| Model | Bảng | Nội dung |
| --- | --- | --- |
| `LineageEdge` | `lineage_edges` | Cạnh vẽ tay, hoặc override ẩn/màu cho cạnh suy ra; khóa `(source, target, kind)`, `kind` là `flow`, `relation`, `transform` |
| `LineageCanvas` | `lineage_canvases` | Layout JSON, một dòng cho mỗi database Superset |
| `LineageTransformation` | `lineage_transformations` | Phép biến đổi của một dataset đích: tên (duy nhất theo đích), mô tả, SQL, `origin` (`manual`, `sql_job`, `view_sql`) |
| `LineageTransformationInput` | `lineage_transformation_inputs` | Dataset nguồn của phép biến đổi |
| `LineageColumnDependency` | `lineage_column_dependencies` | Phụ thuộc cột nguồn → cột đích với vai trò `value`, `group`, `join`, `filter` |

Cột được tham chiếu bằng tên kèm dataset ID, không FK tới `table_columns`, vì Superset có thể đổi ID cột khi đồng bộ.
Module không khai báo lại dataset, database hay `ColumnDictionary`; nó đọc alias Superset từ `data_dictionary` và đọc
tham chiếu cột qua repository của module đó.

`ensure_data_lineage_tables()` tạo năm bảng với `checkfirst` dưới advisory lock `74_116_301`, khóa
dùng chung với migration tổng và migration của `data_dictionary`, `business_model`; không sửa bảng Superset. Route đồ thị và xóa cạnh gọi thêm `ensure_data_dictionary_tables()`.

## Đồ thị

`DataLineageService.graph(database_id, datasets)` nhận danh sách dataset của database (route lấy bằng
`datasets_on_database`, rồi service giữ lại dataset người gọi truy cập được) và ghép ba nguồn cạnh:

- Cạnh `relation` suy từ `ColumnDictionary.referenced_dataset_id`/`referenced_column_name`, `origin` là `dictionary`,
  chỉ khi cả hai cột còn tồn tại trong Superset.
- Cạnh `transform` từ mỗi cặp nguồn → đích của phép biến đổi, `origin` là `origin` của phép biến đổi, `label` là tên,
  kèm `transformation_id` và các phụ thuộc cột của nguồn đó.
- Cạnh vẽ tay (`origin` là `manual`) trong `lineage_edges`. Override trong cùng bảng đổi màu hoặc ẩn cạnh suy ra.

Phép biến đổi chỉ hiện khi người gọi thấy cả dataset đích và mọi nguồn. Cùng payload được nhúng vào
`GET /business-model/databases/<id>` dưới khóa `lineage`.

## Quy tắc

- Đọc cần `can_view`; dataset ngoài quyền truy cập Superset bị bỏ khỏi kết quả.
- Tạo, sửa phép biến đổi cần quyền sửa (`can_edit` cộng truy cập dataset) trên dataset đích và mọi nguồn; xóa chỉ cần
  quyền sửa dataset đích. Đích không được nằm trong danh sách nguồn; nguồn không trùng. SQL tối đa 1 MB; `sql_job` và
  `view_sql` cần SQL; `view_sql` chỉ dùng khi đích là view hoặc materialized view. Cột nguồn phải thuộc dataset nguồn
  đã chọn, cột đích thuộc dataset đích; vai trò `value` phải có cột đích; không lặp phụ thuộc.
- Lưu phép biến đổi thay toàn bộ nguồn và phụ thuộc cột.
- `sql_preview.py` chỉ phân tích một câu SELECT bằng SQLGlot để gợi ý nguồn và phụ thuộc cột; CTE, subquery và UNION
  trả cảnh báo và `complete: false`. Đọc SQL của view dùng SQLAlchemy Inspector trên engine Superset của database. Module
  không chạy SQL client gửi.
- Cạnh vẽ tay và màu cạnh cần quyền sửa cả hai dataset, hai dataset phải cùng database. Xóa cạnh suy ra chỉ ẩn nó; xóa
  cạnh vẽ tay xóa dòng. Lưu canvas cần role `Admin`.

## Lớp module

- `repositories/`: truy vấn cạnh, canvas, phép biến đổi.
- `services/srv_data_lineage.py`: dựng đồ thị, áp override, lưu canvas và cạnh, quản lý phép biến đổi; không đọc Flask
  request và không commit.
- `services/sql_preview.py`: phân tích SQL.
- `routes/route_data_lineage.py`: `DataLineageAPI`, kiểm tra payload và quyền, commit hoặc rollback.
- `dependencies.py`: tạo service trên `superset.extensions.db.session`.

## Giao diện

Menu **Mô hình dữ liệu**, mục **Dòng dữ liệu** (`/text-to-bi/?section=lineage&database=<id>`, thêm `&dataset=<id>`
để mở sẵn một bảng), cần `can_view`; mã ở `frontend/src/features/data-lineage/`.

- Màn hình đọc `GET /business-model/databases/<id>` (bảng, tầng), `GET /data-lineage/graph` (cạnh) và
  `GET /data-lineage/transformations`.
- Cột trái liệt kê bảng và phép biến đổi. Canvas tự xếp bảng bằng ELK theo chiều dòng dữ liệu, với ba mức chi tiết:
  **Bảng**, **Cột liên quan**, **Tất cả cột** (cột lấy từ từ điển). Chọn một bảng, phép biến đổi hoặc cột sẽ tô sáng
  nguồn và nơi dùng của nó; nhấp đúp bảng mở **Từ điển**.
- User có `can_edit` mở trình soạn phép biến đổi: chọn bảng đích, nguồn, loại nguồn, dán SQL rồi **Phân tích SQL**
  (gọi `/preview`) hoặc **Đọc SQL của view**, chỉnh liên kết cột, lưu hoặc xóa.
- Mục **Tổng quan** có thẻ thống kê dòng dữ liệu của database đang chọn.

Canvas không lưu vị trí bảng đã kéo. Các route `PUT /canvas` và `POST|PUT|DELETE /edges` có hàm gọi sẵn trong
`features/data-lineage/api.ts` nhưng chưa màn hình nào dùng.
