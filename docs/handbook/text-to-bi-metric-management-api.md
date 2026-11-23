# Metric Management API

API class `TextToBIMetricAPI` (`resource_name="metrics"`), đường dẫn `/extensions/text-to-bi/superset-text-to-bi/metrics`. Mọi route cần phiên Superset đã đăng nhập và quyền chung `text_to_bi_api` (`can_read` cho GET, `can_write` cho thao tác ghi). Thao tác ghi cần header `X-CSRFToken`. Service kiểm tra thêm quyền Text to BI và quyền đọc dataset của Superset. Lỗi trả `{code, message}`.

| Method và path | Quyền bổ sung | Request và kết quả |
| --- | --- | --- |
| `GET /datasets/<dataset_id>` | Xem Text to BI (`require_view`), đọc dataset | `200 {metrics}`: metric tự tạo (`origin="manual"`) và metric Superset (`origin="superset"`) của dataset, sắp theo tên. |
| `GET /<metric_uuid>` | Xem Text to BI, đọc dataset của metric | `200 {metric}`. UUID sai trả `422`, không thấy trả `404`. |
| `POST /` | Sửa Text to BI (`require_edit`) trên dataset | Body `MetricCreate`; tạo metric `draft`, trả `201 {metric}`. Trùng tên trả `409`. |
| `PATCH /<metric_uuid>` | Sửa Text to BI trên dataset | Body `MetricPatch`; chỉ cập nhật field có gửi, trả `200 {metric}`. Đổi nội dung đưa metric về `draft`. |
| `POST /<metric_uuid>/approve` | Review (`require_review`: Steward hoặc Admin), đọc dataset | Không body; metric phải đang `draft`, trả `200 {metric}`. |
| `POST /<metric_uuid>/revoke` | Review, đọc dataset | Không body; metric phải đang `approved`, trả `200 {metric}`. |
| `DELETE /<metric_uuid>` | Sửa Text to BI trên dataset; metric `approved` cần thêm review | `200 {message}`. |

`MetricCreate`: `dataset_id` (> 0), `name` (1–255), `expression` (1–10.000); tùy chọn `label` (≤ 255), `description`, `format` (≤ 128), `currency` (≤ 16), `metric_type` (≤ 64), `warning_text`, `business_domain_ids` (≤ 50 UUID, phải tồn tại trong `business_domains`). `MetricPatch` nhận các field trên trừ `dataset_id`, thêm `is_active`; `name`, `expression`, `is_active` không được gửi `null`. Service bỏ khoảng trắng đầu/cuối của tên và biểu thức, từ chối biểu thức có dấu `;`.

Metric trả về gồm `id`, `origin`, `dataset_id`, `name`, `label`, `expression`, `description`, `format`, `currency`, `metric_type`, `warning_text`, `is_active`, `status`, `business_domains` (`{id, name, color}`), `created_at`, `updated_at`. Metric Superset lấy `label` từ `verbose_name`, `format` từ `d3format`, luôn `status="approved"`, không sửa được qua API này.

Mỗi lần ghi metric (và mỗi lần Superset ghi `sql_metrics`) tạo job lập chỉ mục Text2SQL cho database của dataset; xem [Text2SQL API](text-to-bi-text2sql-api.md).
