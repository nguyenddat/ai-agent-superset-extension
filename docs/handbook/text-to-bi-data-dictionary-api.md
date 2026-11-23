# Data Dictionary API của Text to BI

Base resource: `/extensions/text-to-bi/superset-text-to-bi/data-dictionary`.

Nguồn: [routes](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_dictionary/routes/route_data_dictionary.py),
[schemas](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_dictionary/schemas/schema_data_dictionary.py),
[service](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_dictionary/services/dictionary_service.py).

API chỉ quản lý phần mô tả nghiệp vụ của extension; dataset, cột và việc đồng bộ cột vẫn qua API và màn hình của
Superset. Mọi route cần phiên Superset và permission `can_read` (GET) hoặc `can_write` (ghi) trên `text_to_bi_api`;
route ghi kiểm tra header `X-CSRFToken`. Quy tắc nghiệp vụ xem [module data_dictionary](text-to-bi-data-dictionary.md).

## Endpoint

| Method | Path | Quyền | Response 200 |
| --- | --- | --- | --- |
| GET | `/summary` | `can_view` | Cây database → schema → dataset người gọi đọc được |
| GET | `/stats?limit=5` | `can_view`; `limit` nguyên 1–20 | Thống kê độ phủ và xếp hạng dataset |
| GET | `/datasets/<dataset_id>` | `can_view` + truy cập dataset | Từ điển của dataset (`TableDictionaryOut`) |
| PUT | `/datasets/<dataset_id>` | `can_edit` + truy cập dataset | Lưu thông tin bảng; trả `TableDictionaryOut` |
| PUT | `/datasets/<dataset_id>/columns` | `can_edit` + truy cập dataset | Lưu các cột gửi lên; trả `TableDictionaryOut` |
| POST | `/datasets/<dataset_id>/autofill` | `can_edit` + truy cập dataset | `text/event-stream` (bên dưới); không có body |

`/summary` và `/stats` dùng `readable_datasets()`: bỏ dataset của database đánh dấu nội bộ (`text_to_bi_internal`
trong `Database.extra`) và dataset người gọi không truy cập được.

## Payload

`PUT /datasets/<dataset_id>` (`TableDictionaryIn`): `display_name` bắt buộc (1–255); tùy chọn `description`,
`grain_description`, `table_kind`, `layout` (mặc định `wide`), `indicator_catalog_dataset_id`, `contains_pii`,
`column_roles` (`{role, qualifier?, column_name}`), `time_grains` (`{row_kind_value?, label?, time_grain}`),
`indicator_aggregations` (`{source_code, aggregation}`). Mỗi danh sách tối đa 50 phần tử. Request thay toàn bộ thông
tin bảng và ba danh sách con.

```json
{
  "display_name": "Đơn hàng",
  "description": "Một dòng cho mỗi đơn hàng",
  "layout": "wide",
  "column_roles": [{"role": "created_at", "column_name": "order_date"}],
  "time_grains": [{"time_grain": "day"}],
  "indicator_aggregations": []
}
```

`PUT /datasets/<dataset_id>/columns` (`ColumnDictionariesIn`): `{"columns": [...]}`, tối đa 1.000 phần tử. Mỗi phần tử
có `column_name`, `display_name` (1–255) và tùy chọn `description`, `business_term`, `semantic_role`, `temporal_kind`,
`unit`, `format`, `is_primary_key`, `is_unique`, `referenced_column` (`{dataset_id, column_name}`), `contains_pii`,
`aggregations` (tối đa 10), `synonyms` (tối đa 50 theo schema, 20 sau khi loại trùng). Một request không được lặp
`column_name`; cột không gửi giữ nguyên.

Mọi body cấm field ngoài schema. Giá trị enum, vai trò bắt buộc theo layout, danh mục chỉ số, cột tham chiếu và giới
hạn độ dài do service kiểm tra; lỗi trả `message` chỉ rõ phần tử, ví dụ `columns[3].referenced_column ...`.

## Response

`TableDictionaryOut`: `dataset_id`, `database_id`, `database_name`, `schema_name`, `table_name`, `dataset_kind`
(`physical`/`virtual`), `can_edit`, `is_saved`, `display_name`, `description`, `grain_description`, `table_kind`,
`layout`, `indicator_catalog` (`{dataset_id, schema_name, table_name, display_name}` hoặc `null`), `contains_pii`,
`updated_at`, `column_roles`, `time_grains`, `indicator_aggregations`, `columns`.

Mỗi phần tử `columns`: `column_name`, `verbose_name`, `data_type`, `is_dttm`, `is_calculated` (lấy từ Superset),
`is_saved`, `display_name`, `description`, `business_term`, `semantic_role`, `semantic_role_is_default`,
`temporal_kind`, `unit`, `format`, `is_primary_key`, `is_unique`, `referenced_column`
(`{dataset_id, schema_name, table_name, column_name}` hoặc `null`), `contains_pii`, `aggregations`, `synonyms`,
`updated_at`.

`/summary`: `{table_count, described_table_count, databases: [{database_id, database_name, schemas: [{schema_name,
tables: [{dataset_id, table_name, dataset_kind, is_saved, display_name, layout, column_count,
described_column_count}]}]}]}`.

`/stats`: `table_count`, `described_table_count`, `column_count`, `described_column_count`, `schemas` (số bảng và số
bảng đã mô tả theo database/schema), `most_columns` và `most_referenced` (tối đa `limit` dataset; `most_referenced`
đếm số bảng khác tham chiếu tới dataset).

## Tự động điền qua SSE

`POST /datasets/<dataset_id>/autofill` kiểm tra trước khi mở stream: dataset phải có cột, tối đa 300 cột, mô hình ngôn
ngữ đã cấu hình, dataset không đang được tự động điền. Lỗi ở bước này trả JSON `{code, message}` như mọi route.

Khi stream đã mở, sự kiện lần lượt là:

| Event | Data |
| --- | --- |
| `status` | `{processed, total, message}` |
| `columns` | `{columns: ColumnDictionaryOut[], processed, total}` cho mỗi lô cột đã lưu |
| `table` | `TableDictionaryOut` sau khi điền thông tin bảng |
| `done` | `{processed, total, failed_columns, table_filled}` |
| `error` | `{code, message}`; stream kết thúc, các lô đã gửi vẫn được lưu |

Mỗi lô được commit trước khi phát sự kiện. Client ngắt kết nối giữa chừng thì lock của dataset vẫn được nhả. Client
đọc response theo SSE, không parse như JSON.

## Lỗi

| Status | `code` | Khi nào |
| --- | --- | --- |
| 403 | `view_permission_required`, `edit_permission_required`, `dataset_access_required` | Thiếu quyền |
| 403 | `csrf_token_invalid` | Thiếu hoặc sai CSRF token |
| 404 | `dataset_not_found` | Dataset không tồn tại hoặc người gọi không thấy |
| 409 | `dictionary_autofill_in_progress` | Dataset đang được tự động điền |
| 422 | `invalid_request` | Body sai schema |
| 422 | `invalid_query_parameter` | `limit` không phải số nguyên 1–20 |
| 422 | `invalid_data_dictionary` | Lỗi nghiệp vụ từ điển; dataset chưa có cột hoặc quá 300 cột khi tự động điền |
| 502 | `dictionary_autofill_failed` | Mô hình không trả gợi ý hợp lệ nào (thường gặp dưới dạng event `error`) |
| 503 | `dictionary_autofill_unavailable` | Chưa cấu hình `OPENROUTER_API_KEY`, hoặc nhà cung cấp từ chối key/hết hạn mức |
| 500 | `internal_error` | Lỗi không dự kiến trước khi stream; sau khi stream mở là event `error` |
