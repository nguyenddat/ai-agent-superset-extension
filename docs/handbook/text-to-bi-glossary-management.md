# Glossary Management

`glossary_management` lưu thuật ngữ nghiệp vụ theo dataset Superset, lịch sử revision và các liên kết tri thức. Bản nháp mới không thay revision đã duyệt trong discovery; mọi thao tác ghi dùng optimistic concurrency với `expected_revision`.

## Chủ sở hữu model và bảng

- `GlossaryTerm`, `GlossaryRevision` và `GlossaryLink` là model do module này sở hữu, trong schema `text_to_bi`.
- `GlossaryTerm.dataset_id` tham chiếu `SupersetDataset.id`, model chuẩn import từ `modules.data_dictionary.models`.
- Liên kết cột lưu tên cột ổn định, không lưu `table_columns.id` vì Superset có thể tạo lại bản ghi cột khi đồng bộ dataset.
- `glossary_term_domains` là bảng nối thuộc Glossary Management; `business_domains` thuộc module business model. Migration chỉ tạo bảng nối khi model owner được đăng ký trong metadata.
- Metric thủ công và native được phân giải qua public `MetricService.resolve`; Glossary không định nghĩa lại model metric.

Revision giữ định nghĩa, synonyms, trạng thái và các links của đúng phiên bản. Trạng thái là `draft`, `approved` hoặc `revoked`. Khi nội dung thay đổi, tạo revision nháp mới; khi thu hồi, tạo revision `revoked` từ nội dung đang được phục vụ. Discovery chỉ trả thuật ngữ có revision được duyệt gần nhất và không bị thu hồi.

## Lớp module

- `models/glossary.py`: ba model glossary và bảng nối domain.
- `repositories/`: một repository cho từng model; chỉ repository truy vấn các bảng glossary.
- `services/glossary_service.py`: lifecycle, kiểm tra links còn hợp lệ trên dataset, optimistic revision, quyền truy cập và discovery. Service không đọc request và không commit.
- `dependencies.py`: khởi tạo service trên `superset.extensions.db.session`.
- `routes/route_glossary.py`: xác thực payload, kiểm tra quyền, gọi service, CSRF và transaction.
- `migrations.py`: gọi migration Metric Management (để resolver metric có bảng cần thiết), sau đó chỉ tạo bảng glossary; dùng advisory lock và `checkfirst`.

## API và quyền

Base resource là `/extensions/text-to-bi/superset-text-to-bi/glossary`:

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/datasets/<dataset_id>` | Danh sách thuật ngữ, yêu cầu quyền xem và đọc dataset |
| GET | `/datasets/<dataset_id>/discovery` | Chỉ thuật ngữ có nội dung đang được phục vụ |
| GET | `/<term_id>` | Đọc thuật ngữ và revision hiện tại/đang phục vụ |
| GET | `/<term_id>/revisions` | Xem lịch sử revision |
| POST | `/` | Tạo thuật ngữ với revision nháp đầu tiên; cần quyền sửa dataset |
| PUT | `/<term_id>` | Tạo revision nháp hoặc cập nhật gán domain; cần `expected_revision` |
| POST | `/<term_id>/approve` | Duyệt revision nháp hiện tại; cần Text to BI Steward hoặc Admin |
| POST | `/<term_id>/revoke` | Thu hồi thuật ngữ đang được phục vụ; cần Steward hoặc Admin |
| DELETE | `/<term_id>` | Xóa thuật ngữ; xóa thuật ngữ đang được phục vụ cần Steward hoặc Admin |

Liên kết hợp lệ: `table` với dataset ID, `column` với tên cột hiện có trên dataset, `metric` với metric thủ công đã duyệt/hoạt động, và `superset_metric` với metric native thuộc cùng dataset. Mọi thao tác ghi cần CSRF token; quyền Superset trên dataset được áp dụng song song với quyền Text to BI.

## Tích hợp và migration

`entrypoint.py` đăng ký `TextToBIGlossaryAPI`. `ensure_glossary_tables()` gọi `ensure_metric_tables()` trước để `MetricService.resolve()` hoạt động cả khi Metric API chưa được gọi trong worker hiện tại. Migration không tạo/sửa bảng Superset và không tạo `business_domains`.

Module khác gọi public `GlossaryService.serving_revision()` và `live_links()` hoặc service factory của module; không truy vấn các bảng glossary trực tiếp. Khi Business Model được thêm, entrypoint phải import model owner `BusinessDomain` trước lần migration đầu tiên để tạo bảng nối domain.
