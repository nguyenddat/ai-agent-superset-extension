# Metric Management API

Resource `metrics` được phục vụ dưới `/api/v1/extensions/text-to-bi/superset-text-to-bi/metrics`. Route yêu cầu phiên đăng nhập và quyền `read`/`write` của resource; quyền dataset Superset cũng được kiểm tra trong service. Request ghi cần CSRF token.

| Method và path | Quyền bổ sung | Request và kết quả |
| --- | --- | --- |
| `GET /datasets/<dataset_id>` | `require_view` và quyền đọc dataset | Trả `{metrics}` gồm metric thủ công cùng metric native Superset của dataset. |
| `GET /<metric_uuid>` | `require_view` và quyền đọc dataset sở hữu metric | Trả `{metric}`; UUID không hợp lệ hoặc không tìm thấy trả lỗi tương ứng. |
| `POST /` | Quyền sửa dataset | Body `MetricCreate`; tạo metric `draft`, trả `{metric}` với 201. |
| `PATCH /<metric_uuid>` | Quyền sửa dataset | Body `MetricPatch`; chỉ cập nhật field gửi lên, trả `{metric}`. Thay nội dung nghiệp vụ đưa metric về `draft`. |
| `POST /<metric_uuid>/approve` | Reviewer/Steward hoặc Admin (`require_review`) | Không cần body; duyệt metric `draft`, trả `{metric}`. |
| `POST /<metric_uuid>/revoke` | Reviewer/Steward hoặc Admin (`require_review`) | Không cần body; thu hồi metric `approved`, trả `{metric}`. |
| `DELETE /<metric_uuid>` | Quyền sửa dataset; metric đã duyệt cần `require_review` | Xóa metric; trả thông báo xác nhận. |

`MetricCreate` yêu cầu `dataset_id` dương, `name` (1–255), `expression` (1–10.000); có thể gửi `label`, `description`, `format`, `currency`, `metric_type`, `warning_text`, và tối đa 50 `business_domain_ids` UUID. `MetricPatch` nhận các field tương ứng cùng `is_active`; `name`, `expression`, `is_active` không được gửi thành `null`. Service chuẩn hóa khoảng trắng ở tên/công thức, từ chối tên trống, công thức trống/quá dài hoặc có dấu chấm phẩy, và giữ tên duy nhất trong dataset.

Metric thủ công thuộc bảng extension `text_to_bi.metrics`. Metric native được đọc trực tiếp từ Superset `sql_metrics` qua model chuẩn do module Superset/Data Dictionary cung cấp; không có bản sao extension. Module này quản lý metadata, không thực thi SQL metric hay đồng bộ database Superset. Metric resolver dùng chung có thể phân giải metric thủ công đã duyệt và metric native cho Glossary/Expert Rule.
