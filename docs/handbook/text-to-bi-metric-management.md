# Metric Management

`metric_management` quản lý metric do người dùng tạo trên dataset Superset và đọc metric native Superset để hiển thị/hỗ trợ module khác. Module chưa thực thi SQL metric; kết quả query thuộc quy trình riêng.

## Chủ sở hữu model và bảng

- `Metric` là model extension trong schema `text_to_bi`, bảng `metrics`, dùng UUID v7 và audit columns từ `AuditedModel`.
- `dataset_id` tham chiếu `SupersetDataset.id`, model chuẩn được import từ `modules.data_dictionary.models`; không định nghĩa lại bảng `tables`.
- Metric native là `SupersetMetric` (`sql_metrics`), alias được export bởi `modules.data_dictionary.models`. Chỉ đọc trực tiếp; không sao chép vào `text_to_bi.metrics`.
- `metric_domains` là bảng liên kết do Metric Management khai báo. `business_domains` thuộc module business model; association chỉ được migration tạo khi model owner đã đăng ký trong metadata. Metric Management không tạo lại model domain.

Các field metric thủ công gồm tên, biểu thức, nhãn, mô tả, định dạng, tiền tệ, loại metric, cảnh báo, trạng thái và cờ hoạt động. Trạng thái hợp lệ: `draft`, `approved`, `revoked`. Sửa nội dung nghiệp vụ đưa metric về `draft`; chỉ metric `approved` và đang hoạt động được `resolve` cho module glossary/expert rule.

## Lớp module

- `models/metric.py`: model `Metric` và bảng liên kết domain.
- `repositories/metric_repository.py`: CRUD metric thủ công, tìm tên không phân biệt hoa thường và truy vấn `SupersetMetric` native.
- `services/metric_service.py`: kiểm tra quyền dataset, uniqueness, validation, duyệt/thu hồi, domain assignment, serialization và public resolver cho module khác.
- `dependencies.py`: tạo `MetricService` từ `superset.extensions.db.session`.
- `routes/route_metric.py`: xác thực payload, kiểm tra quyền, gọi service và sở hữu transaction.
- `migrations.py`: tạo bảng riêng của module trong schema `text_to_bi`; advisory lock và `checkfirst` giúp migration idempotent/an toàn giữa worker.

## API và quyền

Base resource là `/extensions/text-to-bi/superset-text-to-bi/metrics`:

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/datasets/<dataset_id>` | Danh sách metric thủ công và native Superset; yêu cầu quyền xem và quyền đọc dataset |
| GET | `/<metric_id>` | Đọc chi tiết metric thủ công |
| POST | `/` | Tạo metric nháp; yêu cầu quyền sửa dataset |
| PATCH | `/<metric_id>` | Cập nhật metric; thay nội dung nghiệp vụ thì trả về `draft` |
| POST | `/<metric_id>/approve` | Duyệt nháp; yêu cầu Text to BI Steward hoặc Admin |
| POST | `/<metric_id>/revoke` | Thu hồi metric đã duyệt; yêu cầu Steward hoặc Admin |
| DELETE | `/<metric_id>` | Xóa metric; xóa metric đã duyệt cần Steward hoặc Admin |

Mọi thao tác ghi cần CSRF token. Superset quyền truy cập dataset vẫn được áp dụng cùng quyền Text to BI.

## Gọi từ module khác

Module khác import `Metric`/`metric_domains` từ `modules.metric_management.models`, hoặc gọi `MetricService.resolve(kind, target_key, dataset_id)` để phân giải metric thủ công đã duyệt và metric native. Không query bảng metric từ route/module khác và không khai báo lại model SupersetMetric.

Khi Business Model được tích hợp, entrypoint phải import model owner `BusinessDomain` trước migration đầu tiên để FK của `metric_domains` được resolve và bảng association được tạo. Migration Metric Management không quản lý bảng `business_domains`.
