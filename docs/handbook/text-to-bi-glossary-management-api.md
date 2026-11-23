# Glossary Management API

API class `TextToBIGlossaryAPI` (`resource_name="glossary"`), đường dẫn `/extensions/text-to-bi/superset-text-to-bi/glossary`. Mọi route cần phiên Superset đã đăng nhập và quyền chung `text_to_bi_api` (`can_read` cho GET, `can_write` cho thao tác ghi). Thao tác ghi cần header `X-CSRFToken`. Service kiểm tra quyền Text to BI và quyền đọc dataset của Superset. Lỗi trả `{code, message}`; `expected_revision` lệch revision hiện tại trả `409`.

| Method và path | Quyền bổ sung | Request và kết quả |
| --- | --- | --- |
| `GET /datasets/<dataset_id>` | Xem Text to BI (`require_view`), đọc dataset | `200 {terms}`: mọi thuật ngữ của dataset. |
| `GET /datasets/<dataset_id>/discovery` | Xem Text to BI, đọc dataset | `200 {terms}`: thuật ngữ có bản đang phục vụ, mỗi mục `{id, name, definition, synonyms, business_domains, links}` với liên kết còn sống. |
| `GET /<term_uuid>` | Xem Text to BI, đọc dataset của thuật ngữ | `200 {term}`. |
| `GET /<term_uuid>/revisions` | Xem Text to BI, đọc dataset của thuật ngữ | `200 {revisions}`, mới nhất trước. |
| `POST /` | Sửa Text to BI (`require_edit`) trên dataset | Body `GlossaryCreate`; tạo thuật ngữ và revision 1 `draft`, trả `201 {term}`. Trùng tên trả `409`. |
| `PUT /<term_uuid>` | Sửa Text to BI trên dataset | Body `GlossaryUpdate`; tạo revision `draft` mới khi nội dung đổi hoặc revision hiện tại đã `revoked`; cập nhật miền nghiệp vụ. Trả `200 {term}`. |
| `POST /<term_uuid>/approve` | Review (`require_review`: Steward hoặc Admin) | Body `{expected_revision}`; revision hiện tại phải là `draft`. Trả `200 {term}`. |
| `POST /<term_uuid>/revoke` | Review | Body `{expected_revision}`; cần có bản đang phục vụ; tạo revision `revoked`. Trả `200 {term}`. |
| `DELETE /<term_uuid>` | Sửa Text to BI trên dataset; có bản đang phục vụ thì cần thêm review | `200 {message}`. |

`GlossaryCreate`: `dataset_id` (> 0), `canonical_name` (1–255), `definition` (1–10.000), `synonyms` (≤ 50, mỗi mục ≤ 255 sau khi gộp khoảng trắng, không trùng nhau hay trùng tên chuẩn), `links` (≤ 100), `business_domain_ids` (≤ 50 UUID). `GlossaryUpdate` nhận `definition`, `synonyms`, `links`, `business_domain_ids` và `expected_revision` (≥ 1); không đổi được tên. Một link là `{kind, target_key}` với `kind` thuộc `table`, `column`, `metric`, `superset_metric` và `target_key` 1–300 ký tự; link không thuộc dataset, không còn tồn tại hoặc bị trùng trả `422`.

`term` gồm `id`, `dataset_id`, `canonical_name`, `business_domains`, `current` (revision mới nhất), `serving` (bản đang phục vụ hoặc `null`), `created_at`, `updated_at`. Một revision gồm `number`, `status`, `definition`, `synonyms`, `links`, `created_at`.
