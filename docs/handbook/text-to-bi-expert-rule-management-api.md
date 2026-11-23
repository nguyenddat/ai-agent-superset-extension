# Expert Rule Management API

API class `TextToBIExpertRuleAPI` (`resource_name="expert-rules"`), đường dẫn `/extensions/text-to-bi/superset-text-to-bi/expert-rules`. Mọi route cần phiên Superset đã đăng nhập và quyền chung `text_to_bi_api` (`can_read` cho GET, `can_write` cho thao tác ghi). Thao tác ghi cần header `X-CSRFToken`. Service kiểm tra quyền Text to BI và quyền đọc dataset của Superset. Lỗi trả `{code, message}`; `expected_revision` lệch revision hiện tại trả `409`.

| Method và path | Quyền bổ sung | Request và kết quả |
| --- | --- | --- |
| `GET /datasets/<dataset_id>` | Xem Text to BI (`require_view`), đọc dataset | `200 {rules}`: mọi quy tắc của dataset. |
| `GET /datasets/<dataset_id>/discovery` | Xem Text to BI, đọc dataset | `200 {rules}`: quy tắc có bản đang phục vụ và còn sống, mỗi mục `{id, dataset_id, name, business_domains, description, conditions, exceptions, examples, glossary_term_ids, metric_refs}`. |
| `GET /datasets/<dataset_id>/options` | Xem Text to BI, đọc dataset | `200 {options}`: `{dataset_id, columns: [{name, data_type}], glossary_terms: [{id, name}], metrics}` với thuật ngữ đang phục vụ và metric đang hoạt động (gồm metric Superset). |
| `GET /<rule_uuid>` | Xem Text to BI, đọc dataset của quy tắc | `200 {rule}`. |
| `GET /<rule_uuid>/revisions` | Xem Text to BI, đọc dataset của quy tắc | `200 {revisions}`, mới nhất trước. |
| `POST /` | Sửa Text to BI (`require_edit`) trên dataset | Body `RuleCreate`; tạo quy tắc và revision 1 `draft`, trả `201 {rule}`. Trùng tên trả `409`. |
| `PUT /<rule_uuid>` | Sửa Text to BI trên dataset | Body `RuleUpdate`; tạo revision `draft` mới khi nội dung đổi hoặc revision hiện tại đã `revoked`; cập nhật miền nghiệp vụ. Trả `200 {rule}`. |
| `POST /<rule_uuid>/approve` | Review (`require_review`: Steward hoặc Admin) | Body `{expected_revision}`; revision hiện tại phải là `draft` và còn sống, nếu không trả `409`. Trả `200 {rule}`. |
| `POST /<rule_uuid>/revoke` | Review | Body `{expected_revision}`; cần có bản đang phục vụ; tạo revision `revoked`. Trả `200 {rule}`. |
| `DELETE /<rule_uuid>` | Sửa Text to BI trên dataset; có bản đang phục vụ thì cần thêm review | `200 {message}`. |

`RuleCreate`: `dataset_id` (> 0), `name` (1–255), `description` (≤ 10.000, tùy chọn), `conditions` (1–50), `exceptions` (≤ 50), `examples` (≤ 50), `glossary_term_ids` (1–50 UUID, không trùng), `metric_refs` (≤ 50, không trùng), `business_domain_ids` (≤ 50 UUID). `RuleUpdate` nhận các field nội dung, `business_domain_ids` và `expected_revision` (≥ 1); không đổi được tên.

- Condition: `{column_name (1–255), operator, value_type, value}`. `operator` thuộc `equals`, `not_equals`, `contains`, `not_contains`, `greater_than`, `greater_than_or_equal`, `less_than`, `less_than_or_equal`, `in`, `not_in`, `is_null`, `is_not_null`; `value_type` thuộc `string`, `number`, `boolean`, `null`, `array`. `value` phải đúng kiểu; `in`/`not_in` cần mảng không rỗng; `contains`/`not_contains` cần chuỗi; so sánh lớn/nhỏ cần số; `is_null`/`is_not_null` cần `null`.
- Exception: `{when, outcome}`; example: `{question, intent}`; mỗi field 1–2.000 ký tự.
- Metric ref: `{kind: "metric" | "superset_metric", target_key (1–40)}`.

Cột ngoài dataset, thuật ngữ khác dataset hoặc chưa có bản phục vụ liên kết tới dataset, metric không phân giải được đều trả `422`.

`rule` gồm `id`, `dataset_id`, `name`, `business_domains`, `current`, `serving` (hoặc `null`), `is_discoverable`, `created_at`, `updated_at`. Một revision gồm `number`, `status`, `description`, `conditions`, `exceptions`, `examples`, `glossary_term_ids`, `metric_refs`, `created_at`.
