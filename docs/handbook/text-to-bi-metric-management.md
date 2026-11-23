# Metric Management

`metric_management` quản lý metric do người dùng tự định nghĩa trên dataset Superset và đọc metric có sẵn của Superset để hiển thị cùng danh sách, cho Glossary, Expert Rule và Text2SQL dùng. Module chỉ lưu biểu thức SQL; không chạy metric. Agent Text2SQL chạy metric qua SQL Lab của Superset (xem [Text2SQL](text-to-bi-text2sql.md)).

## Dữ liệu sở hữu

- `Metric` (bảng `text_to_bi.metrics`, UUID v7, cột audit từ `AuditedModel`): `dataset_id`, `name`, `label`, `expression`, `description`, `format`, `currency`, `metric_type`, `warning_text`, `is_active`, `status`. Tên duy nhất trong một dataset (`uq_metrics_dataset_name`; service so sánh không phân biệt hoa thường).
- `dataset_id` là khóa ngoại tới `SupersetDataset.id` (bảng `tables` của Superset, model import từ `modules.data_dictionary.models`), `ON DELETE CASCADE`.
- `metric_domains` là bảng nối metric với `text_to_bi.business_domains`. Bảng miền nghiệp vụ thuộc module [Business Model](text-to-bi-business-model.md).
- Metric Superset (`SupersetMetric`, bảng `sql_metrics`) chỉ được đọc; không sao chép vào `text_to_bi.metrics`. API trả nó với `origin="superset"`, `status="approved"`, `is_active=true`, không có miền nghiệp vụ.

## Vòng đời

- Trạng thái metric tự tạo: `draft` → `approved` → `revoked`. Tạo mới luôn là `draft`.
- Chỉ duyệt được metric `draft`; chỉ thu hồi được metric `approved`. Cả hai cần quyền review (Text to BI Steward hoặc Admin).
- Sửa `name`, `expression`, `label`, `description`, `format`, `currency`, `metric_type` hoặc `warning_text` (giá trị khác giá trị cũ) đưa metric về `draft`. Đổi `is_active` hoặc miền nghiệp vụ không đổi trạng thái. Metric `revoked` sửa nội dung thì quay về `draft` để duyệt lại.
- Xóa metric cần quyền sửa dataset; xóa metric đang `approved` cần thêm quyền review.
- Service chuẩn hóa khoảng trắng đầu/cuối của tên và biểu thức, từ chối tên trống, biểu thức trống, dài hơn 10.000 ký tự hoặc có dấu `;`.
- `MetricService.resolve(kind, target_key, dataset_id)` chỉ trả metric tự tạo `approved`, `is_active` và cùng dataset (`kind="metric"`, `target_key` là UUID), hoặc metric Superset cùng dataset (`kind="superset_metric"`, `target_key` là ID số). Glossary và Expert Rule dùng hàm này để kiểm tra liên kết.
- Text2SQL chỉ lập chỉ mục và dùng metric tự tạo `approved` và đang hoạt động. Mọi thay đổi trên `metrics` hoặc `sql_metrics` tạo job lập chỉ mục cho các topic `metric`, `glossary`, `expert_rule`, `own_knowledge` của database chứa dataset.

## Lớp module

- `models/metric.py`: `Metric` và bảng nối `metric_domains`.
- `repositories/metric_repository.py`: đọc/ghi metric tự tạo, tìm tên không phân biệt hoa thường, đọc `SupersetMetric` của dataset.
- `services/metric_service.py`: quyền dataset, kiểm tra dữ liệu, duyệt/thu hồi, gán miền nghiệp vụ, serialize và `resolve`. Service không đọc request, không commit.
- `dependencies.py`: tạo `MetricService` trên `superset.extensions.db.session`.
- `routes/route_metric.py`: `TextToBIMetricAPI`, kiểm tra body, CSRF, commit.
- `migrations.py`: `ensure_metric_tables()` gọi `ensure_business_model_tables()` trước (ngoài `_lock`, vì lần chạy đầu của Business Model gọi ngược chuỗi expert rule → glossary → metric), rồi tạo `metrics` và `metric_domains` dưới advisory lock `74_116_301`; với PostgreSQL còn thêm cột `status` nếu bảng cũ chưa có.

## API và quyền

Resource `/extensions/text-to-bi/superset-text-to-bi/metrics`; chi tiết ở [Metric Management API](text-to-bi-metric-management-api.md).

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/datasets/<dataset_id>` | Metric tự tạo và metric Superset của dataset |
| GET | `/<metric_id>` | Chi tiết metric tự tạo |
| POST | `/` | Tạo metric nháp |
| PATCH | `/<metric_id>` | Sửa metric tự tạo |
| POST | `/<metric_id>/approve` | Duyệt metric nháp |
| POST | `/<metric_id>/revoke` | Thu hồi metric đã duyệt |
| DELETE | `/<metric_id>` | Xóa metric tự tạo |

Mọi route cần quyền `can_read`/`can_write` của `text_to_bi_api`. Đọc cần thêm quyền xem Text to BI; ghi cần quyền sửa (Editor, Steward, Admin); duyệt/thu hồi cần quyền review. Quyền đọc dataset của Superset luôn được kiểm tra, kể cả với Admin.

## Giao diện

Mục **Metric** trong menu **Quản trị dữ liệu** (`/text-to-bi/?section=metrics&dataset=<id>`), mở với người có quyền xem. Trang chọn một dataset (mặc định dataset đầu tiên đọc được), hiện bốn ô thống kê (Tổng metric, Tự tạo, Từ Superset, Đã duyệt), ô tìm kiếm, bộ lọc nguồn và danh sách. Metric Superset và người không có quyền sửa chỉ xem chi tiết. Form tạo/sửa có chọn bảng, tên, nhãn, biểu thức (chèn cột từ từ điển dữ liệu), định dạng số, tiền tệ, miền nghiệp vụ. Khối trạng thái hiện nút Duyệt/Thu hồi với người có quyền review. Thẻ **Bảng đã có metric** ở mục Tổng quan đếm metric đang hoạt động theo dataset; frontend gọi `GET /metrics/datasets/<id>` cho từng dataset vì backend chưa có API đếm chung.

## Gọi từ module khác

Module khác import `Metric`/`metric_domains` từ `modules.metric_management.models` hoặc gọi `MetricService` (`resolve`, `list_metrics`, `create_metric`); không truy vấn bảng metric trực tiếp và không khai báo lại `SupersetMetric`. Own Knowledge tạo metric khi promote qua `MetricService.create_metric`.
