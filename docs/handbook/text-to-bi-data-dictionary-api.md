# Data Dictionary API của Text to BI

Module `data_dictionary` lưu phần mô tả nghiệp vụ do người dùng biên tập trong schema extension `text_to_bi`, đồng thời đọc danh mục dataset/cột từ Superset. Các route dưới đây thuộc API extension; module không proxy API REST dataset của Superset.

Nguồn triển khai: [routes](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_dictionary/routes/route_data_dictionary.py), [schemas](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_dictionary/schemas/schema_data_dictionary.py), [models](../../extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_dictionary/models/__init__.py).

## API native Superset và API extension

Superset sở hữu database, dataset (`tables`) và dataset column (`table_columns`). API native Superset vẫn là nơi quản trị/sync dataset và metadata nguồn. Extension đọc những model chuẩn này, dùng Superset DAO/ACL để tìm dataset và lưu dictionary theo `dataset_id`; metadata kiểu dữ liệu, temporal và cột nguồn luôn lấy từ Superset. Dictionary tùy chỉnh lưu trong các bảng `text_to_bi.table_dictionaries`, `column_dictionaries` và bảng con do extension quản lý.

API native Superset dành cho đọc/sửa dataset và đồng bộ cột vẫn có contract riêng của Superset; trang này không mô tả lại contract đó. Các endpoint sau chỉ quản lý business dictionary của extension.

Base resource: `/extensions/text-to-bi/superset-text-to-bi/data-dictionary`.

## Endpoint

| Method | Path | Mục đích và quyền |
| --- | --- | --- |
| GET | `/summary` | Cây database → schema → dataset mà người gọi có quyền đọc; cần quyền xem Text to BI |
| GET | `/stats?limit=5` | Thống kê dictionary và xếp hạng dataset; `limit` nguyên từ 1 đến 20; cần quyền xem |
| GET | `/datasets/<dataset_id>` | Đọc dictionary cùng metadata dataset/cột của Superset; cần quyền xem và ACL đọc dataset |
| PUT | `/datasets/<dataset_id>` | Lưu mô tả dataset, layout, vai trò cột, time grain, indicator metadata; cần quyền sửa và ACL đọc dataset |
| PUT | `/datasets/<dataset_id>/columns` | Thay metadata cho các cột gửi lên; cần quyền sửa và ACL đọc dataset |
| POST | `/datasets/<dataset_id>/autofill` | Gợi ý mô tả bằng mô hình ngôn ngữ và trả SSE; cần quyền sửa, ACL đọc dataset và CSRF |

Text to BI Viewer được đọc; Editor và Steward có quyền sửa theo role service; Admin có quyền Text to BI nhưng vẫn chịu ACL dataset Superset. Mỗi thao tác kiểm tra dataset được yêu cầu qua Superset DAO, tránh lộ dataset không có quyền truy cập.

## Payload ghi dữ liệu

`PUT /datasets/<dataset_id>` yêu cầu `display_name` không rỗng (tối đa 255 ký tự). Các thuộc tính tùy chọn gồm `description`, `grain_description`, `table_kind`, `layout` (mặc định `wide`), `indicator_catalog_dataset_id`, `contains_pii`, `column_roles`, `time_grains`, `indicator_aggregations`. Mỗi danh sách con tối đa 50 phần tử. Field không nằm trong schema bị từ chối.

Ví dụ rút gọn:

```json
{
  "display_name": "Đơn hàng",
  "description": "Một dòng cho mỗi đơn hàng",
  "layout": "wide",
  "column_roles": [],
  "time_grains": [],
  "indicator_aggregations": []
}
```

Service kiểm tra enum của `layout`, `table_kind`, role, qualifier, time grain và aggregation; column name phải thuộc dataset. Các role bắt buộc/phù hợp phụ thuộc layout. Indicator catalog phải là dataset khác, cùng database, đã được mô tả với layout `indicator_catalog`; danh sách indicator aggregation chỉ hợp lệ với layout catalog tương ứng. Mô tả và grain description tối đa 2.000 ký tự. Synonym được loại trùng và giới hạn tối đa 20 từ mỗi cột.

`PUT /datasets/<dataset_id>/columns` nhận object `{ "columns": [...] }`, tối đa 1.000 item. Mỗi item có `column_name`, `display_name` và trường tùy chọn `description`, `business_term`, `semantic_role`, `temporal_kind`, `unit`, `format`, `is_primary_key`, `is_unique`, `referenced_column`, `contains_pii`, `aggregations`, `synonyms`. `referenced_column` có dạng `{ "dataset_id": 42, "column_name": "customer_id" }`; dataset đích phải đọc được và cột phải tồn tại. Một request không được lặp `column_name`; các cột không có trong request giữ nguyên. Schema giới hạn aggregation tối đa 10 và synonym tối đa 50 mỗi cột; service áp dụng kiểm tra ngữ nghĩa bổ sung.

Response dataset gồm `dataset_id`, database/schema/table, loại dataset, `can_edit`, `is_saved`, nội dung dictionary, `column_roles`, `time_grains`, `indicator_aggregations` và `columns`. Mỗi cột cho biết metadata nguồn Superset (`data_type`, `is_dttm`, calculated) cùng giá trị dictionary và cờ `is_saved`/`semantic_role_is_default`. Endpoint summary trả `table_count`, `described_table_count` và nhóm database/schema; stats thêm số cột, số cột mô tả, schema và top dataset nhiều cột/được tham chiếu.

## Autofill dạng Server-Sent Events

`POST /datasets/<dataset_id>/autofill` trả `text/event-stream`. Event chuẩn gồm `status`, `columns`, `table`, `done`; lỗi trong lúc stream trả event `error` với `code` và `message`. Event/batch đã gửi được commit trước khi phát ra; lỗi sau khi bắt đầu stream không đổi HTTP status ban đầu mà thể hiện trong event `error`. Client nên đọc response theo SSE, không parse như JSON thông thường.

Autofill cần cấu hình nhà cung cấp LLM. Dataset đang được autofill sẽ nhận conflict thay vì chạy song song; giới hạn tối đa 300 cột. Lỗi trước khi stream được xử lý qua response API thông thường; lỗi trong stream dùng event `error`.

## CSRF, validation và status

Mọi request ghi cần CSRF của Superset; gửi cookie phiên và `X-CSRFToken`. Payload dùng Pydantic, cấm field ngoài schema. `limit` ngoài khoảng 1–20 hoặc body sai trả `422` (code `invalid_request` hoặc `invalid_query_parameter`); lỗi nghiệp vụ dictionary trả `422 invalid_data_dictionary`. CSRF sai trả `403 csrf_token_invalid`. Dataset không tồn tại trả `404 dataset_not_found`; thiếu quyền xem/sửa hoặc ACL dataset trả `403`. Autofill chưa sẵn sàng trả `503 dictionary_autofill_unavailable`, đang chạy trả `409 dictionary_autofill_in_progress`, không tạo được gợi ý hợp lệ trả `502 dictionary_autofill_failed`. Lỗi không dự kiến trước khi stream trả `500`; lỗi sau khi stream bắt đầu được mã hóa trong SSE `error`.

Route gọi migration idempotent để tạo riêng bảng extension trước khi đọc/ghi; migration không tạo hoặc sửa bảng Superset. Superset tiếp tục là nguồn chuẩn cho dataset và column metadata.
