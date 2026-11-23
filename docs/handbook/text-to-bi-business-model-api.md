# API Business Model

Base resource: `/extensions/text-to-bi/superset-text-to-bi/business-model`.

Nguồn: [routes](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/business_model/routes/route_business_model.py),
[schemas](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/business_model/schemas/schema_business_model.py),
[service](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/business_model/services/srv_business_model.py).

Mọi route cần phiên Superset và permission `can_read` (GET) hoặc `can_write` (ghi) trên `text_to_bi_api`; route ghi
kiểm tra header `X-CSRFToken`. `dataset_id` và `database_id` là ID Superset; `layer_id`, `domain_id` là UUID. Quy tắc
nghiệp vụ và màn hình dùng API xem [Business model](text-to-bi-business-model.md).

## Endpoint

| Method | Path | Quyền | Mô tả và response |
| --- | --- | --- | --- |
| GET | `/layers/` | `can_view` | `{layers}`, sắp theo `level`, `sort_order`, tên |
| POST | `/layers/` | Admin | Tạo layer từ `LayerIn`; 201 `{layer}` |
| PUT | `/layers/order` | Admin | Body `{levels: [[uuid, ...], ...]}` (tối đa 100 nhóm), mỗi layer đúng một lần; `{layers}` |
| PUT | `/layers/<layer_id>` | Admin | Thay mọi trường từ `LayerIn`; `{layer}` |
| DELETE | `/layers/<layer_id>` | Admin | Xóa layer, dataset đã gán thành chưa có layer; `{message}` |
| GET | `/domains/` | `can_view` | `{domains}`; mỗi domain chỉ kèm `dataset_ids` mà người gọi truy cập được |
| POST | `/domains/` | Admin + quyền sửa mọi dataset trong `dataset_ids` | Tạo từ `DomainIn`; 201 `{domain}` |
| PUT | `/domains/<domain_id>` | Admin + quyền sửa mọi dataset trong `dataset_ids` | `dataset_ids` thay toàn bộ thành viên; `{domain}` |
| DELETE | `/domains/<domain_id>` | Admin | Xóa domain và thành viên; `{message}` |
| PUT | `/datasets/<dataset_id>/layer` | Quyền sửa dataset | Body `{layer_id: uuid \| null}`; `null` gỡ gán; `{assignment: {dataset_id, layer_id}}` |
| GET | `/databases/<database_id>` | `can_view` | Mô hình tổng hợp của một database (bên dưới) |
| PUT | `/databases/<database_id>/canvas` | Admin | Body `{layout: object}`, JSON tối đa 1 MB; `{canvas: {database_id, layout}}` |

"Quyền sửa dataset" là `can_edit` của Text to BI cộng quyền truy cập dataset trong Superset (`require_edit`).

## Schema

- `LayerIn`: `name` (1–255), `description` (tối đa 2.000), `color` (`#RRGGBB`), `level` và `sort_order` nguyên không
  âm, mặc định 0. Response layer: `{id, name, description, color, level, sort_order}`.
- `DomainIn`: `name` (1–255), `description` (tối đa 2.000), `color` (`#RRGGBB`), `dataset_ids` (tối đa 1.000, không
  trùng, mọi ID phải tồn tại). Dataset chưa có dòng từ điển được tạo dòng `TableDictionary` mới. Response domain:
  `{id, name, description, color, dataset_ids}`.
- Mọi body cấm field ngoài schema. Tên bị cắt khoảng trắng hai đầu; mô tả rỗng thành `null`.

`GET /databases/<database_id>` trả:

- `database_id`, `layers`, `domains` (chỉ thành viên thuộc database này mà người gọi truy cập được).
- `datasets`: các dataset của database mà người gọi truy cập được, mỗi mục
  `{dataset_id, schema, table_name, display_name, table_kind, layer_id, is_classified}`; `display_name` lấy từ từ điển,
  nếu chưa có thì là tên bảng; `is_classified` cho biết dataset đã có dòng từ điển.
- `business_canvas`: layout đã lưu, `{}` nếu chưa có.
- `lineage`: đồ thị dòng dữ liệu, cùng cấu trúc với `GET /data-lineage/graph`
  (xem [Data Lineage API](text-to-bi-data-lineage-api.md)).

Trang Mô hình hiện chỉ gọi `GET /databases/<id>`, `GET /domains/` và các route ghi domain. Route layer, gán layer và
canvas chưa có màn hình.

## Lỗi

| Status | `code` | Khi nào |
| --- | --- | --- |
| 403 | `view_permission_required`, `admin_required`, `edit_permission_required`, `dataset_access_required` | Thiếu quyền |
| 403 | `csrf_token_invalid` | Thiếu hoặc sai CSRF token |
| 404 | `business_model_not_found` | Layer, domain hoặc database không tồn tại |
| 404 | `dataset_not_found` | Dataset không tồn tại hoặc người gọi không thấy |
| 409 | `business_model_conflict` | Trùng tên layer hoặc domain |
| 422 | `business_model_invalid` | Màu sai, tên rỗng, dataset trùng hoặc không tồn tại, thứ tự layer thiếu/thừa, canvas quá 1 MB |
| 422 | `invalid_request` | Body sai schema |
| 500 | `internal_error` | Lỗi không dự kiến, kể cả UUID sai dạng ở đường dẫn, trong `levels` hoặc `layer_id` |
