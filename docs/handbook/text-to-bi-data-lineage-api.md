# Data Lineage API

Base resource: `/extensions/text-to-bi/superset-text-to-bi/data-lineage`.

Nguồn: [routes](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_lineage/routes/route_data_lineage.py),
[schemas](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_lineage/schemas/schema_data_lineage.py),
[service](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_lineage/services/srv_data_lineage.py).

Mọi route cần phiên Superset và permission `can_read` hoặc `can_write` trên `text_to_bi_api` như cột "Permission" ghi.
Route `can_write` kiểm tra header `X-CSRFToken`. Route có `database_id` trên query string yêu cầu số nguyên dương
(thiếu hoặc sai trả 422) và database phải tồn tại qua `DatabaseDAO` (không thì 404). Danh sách dataset của database lấy
bằng `datasets_on_database`, rồi chỉ giữ dataset người gọi truy cập được trong Superset. Mô hình dữ liệu và quy tắc
xem [Data Lineage](text-to-bi-data-lineage.md).

## Endpoint

| Method và path | Permission | Quyền bổ sung | Response 200/201 |
| --- | --- | --- | --- |
| `GET /graph?database_id=` | read | `can_view` | `{database_id, datasets, edges, canvas}` |
| `GET /transformations?database_id=` | read | `can_view` | `{transformations}` |
| `GET /transformations/<uuid>?database_id=` | read | `can_view`; thấy được đích và mọi nguồn | `{transformation}` |
| `POST /transformations?database_id=` | write | Quyền sửa đích và mọi nguồn | 201 `{transformation}` |
| `PUT /transformations/<uuid>?database_id=` | write | Quyền sửa đích và mọi nguồn | `{transformation}` |
| `DELETE /transformations/<uuid>?database_id=` | write | Quyền sửa đích | `{message}` |
| `POST /preview?database_id=` | read | `can_view`; thấy được đích | `{target_dataset_id, source_dataset_ids, dependencies, warnings, complete}` |
| `GET /datasets/<dataset_id>/view-sql?database_id=` | read | `can_view`; truy cập dataset | `{target_dataset_id, sql_text}` |
| `PUT /canvas?database_id=` | write | Role `Admin` | `{database_id}` |
| `POST /edges` | write | Quyền sửa cả hai dataset | `{source, target, kind}` |
| `PUT /edges/color` | write | Quyền sửa cả hai dataset | `{source, target, kind, color}` |
| `DELETE /edges` | write | Quyền sửa cả hai dataset | `{source, target, kind}` |

"Quyền sửa" là `can_edit` của Text to BI cộng quyền truy cập dataset trong Superset (`require_edit`). `POST /preview`
dùng permission `read` và route không gắn bước kiểm tra CSRF riêng; frontend vẫn gửi `X-CSRFToken` như mọi request
không phải GET.

## Đồ thị

`GET /graph` trả:

- `datasets`: `[{id, name, schema, description}]`, sắp theo schema rồi tên bảng.
- `edges`: `[{source, target, kind, origin, label, color, columns}]`, sắp theo source, target, kind.
  - `relation` suy từ từ điển: `origin` là `dictionary`, `columns` là `[{source, target}]`.
  - `transform` từ phép biến đổi: `origin` là `manual`, `sql_job` hoặc `view_sql`, `label` là tên phép biến đổi,
    `columns` là các phụ thuộc của nguồn đó, kèm `transformation_id`.
  - Cạnh vẽ tay: `origin` là `manual`, `columns` rỗng.
- `canvas`: layout đã lưu hoặc `null`.

`GET /business-model/databases/<id>` trả cùng cấu trúc trong khóa `lineage`.

## Phép biến đổi

Body `TransformationIn` cho `POST` và `PUT`:

```json
{
  "target_dataset_id": 12,
  "name": "Tổng hợp doanh thu ngày",
  "description": null,
  "sql_text": "SELECT ...",
  "origin": "sql_job",
  "source_dataset_ids": [7, 9],
  "dependencies": [
    {"source_dataset_id": 7, "source_column_name": "amount", "target_column_name": "revenue", "role": "value"}
  ]
}
```

- `name` 1–255 (chuẩn hóa khoảng trắng), `origin` mặc định `manual`, `source_dataset_ids` 1–500 phần tử, `dependencies`
  tối đa 5.000; `role` là `value`, `group`, `join`, `filter`.
- `PUT` thay toàn bộ nguồn và phụ thuộc; `target_dataset_id` phải trùng với đích hiện có, nếu không trả 404.
- Response `transformation`: `{id, target_dataset_id, name, description, sql_text, origin, source_dataset_ids,
  dependencies, created_at, updated_at}`.

`POST /preview` nhận `{target_dataset_id, sql_text}` (SQL không rỗng, tối đa 1 MB), chỉ phân tích bằng SQLGlot.
`complete` là `false` khi có cảnh báo, ví dụ SQL dùng CTE, subquery hoặc UNION. `GET /datasets/<id>/view-sql` đọc SQL
định nghĩa view hoặc materialized view qua Inspector; dataset phải thuộc `database_id`.

## Canvas và cạnh vẽ tay

`PUT /canvas` nhận `{nodes, edges}`, tổng số mục tối đa 5.000:

- `nodes`: khóa `table-<id>` hoặc `metric-<id>`, giá trị `[x, y]`.
- `edges`: khóa `<flow|relation|transform>-<source>-<target>` hoặc `metric-edge-<n>`, giá trị
  `{style, coords, waypoints, label, ports}`; `style` là `orthogonal`, `straight`, `curved`; tối đa 50 waypoint và 100
  tọa độ; mọi tọa độ có trị tuyệt đối không quá 100.000.

`POST /edges` và `DELETE /edges` nhận `{source, target, kind}`; `PUT /edges/color` thêm `color` (hex 3–8 ký tự hoặc
`null` để bỏ màu). `source`, `target` là ID dataset dương, khác nhau, cùng database; `kind` là `flow`, `relation`,
`transform`. `POST` thêm cạnh vẽ tay hoặc hiện lại cạnh đã ẩn. `DELETE` ẩn cạnh suy ra (từ từ điển hoặc phép biến
đổi) và xóa cạnh vẽ tay. Override `flow`/`relation` khớp cả chiều ngược lại.

## Lỗi

| Status | `code` | Khi nào |
| --- | --- | --- |
| 403 | `view_permission_required`, `edit_permission_required`, `dataset_access_required`, `admin_required` | Thiếu quyền |
| 403 | `csrf_token_invalid` | Thiếu hoặc sai CSRF token |
| 404 | `lineage_database_not_found` | `database_id` không tồn tại |
| 404 | `lineage_transformation_not_found` | Phép biến đổi không có, ngoài phạm vi người gọi thấy, hoặc dataset đích không thuộc database |
| 404 | `dataset_not_found` | Dataset của `view-sql` không tồn tại |
| 409 | `lineage_transformation_conflict` | Trùng tên phép biến đổi trên cùng dataset đích |
| 422 | `data_lineage_validation_error` | Thiếu `database_id`, UUID sai dạng, dataset/cột không hợp lệ, SQL quá 1 MB, dataset không phải view, layout hoặc cạnh sai |
| 422 | `invalid_request` | Body sai schema |
| 500 | `internal_error` | Lỗi không dự kiến; transaction được rollback |
