# API Business Model

API được đăng ký tại `/api/v1/business-model/`. Các thao tác đọc yêu cầu quyền Semantic Layer Viewer (hoặc Admin). Tạo, sửa, xóa layer/domain và lưu canvas yêu cầu Admin cùng header `X-CSRFToken`. Gán layer cho dataset yêu cầu quyền sửa dataset trong Superset. API chỉ trả membership của dataset mà người gọi được truy cập. `dataset_id` và `database_id` là ID trong Superset.

| Method | Path | Mô tả |
| --- | --- | --- |
| GET | `/layers/` | Liệt kê layer theo level, thứ tự và tên. |
| POST | `/layers/` | Tạo layer với `name`, `description`, `color`, `level`, `sort_order`. |
| PUT | `/layers/order` | Sắp xếp lại layer bằng `levels`: danh sách các nhóm UUID; mỗi layer phải xuất hiện đúng một lần. |
| PUT | `/layers/{layer_id}` | Cập nhật các trường layer. |
| DELETE | `/layers/{layer_id}` | Xóa layer; dataset đã gán trở thành chưa phân loại. |
| GET | `/domains/` | Liệt kê domain và các dataset membership người gọi được phép xem. |
| POST | `/domains/` | Tạo domain với `name`, `description`, `color`, `dataset_ids`. |
| PUT | `/domains/{domain_id}` | Cập nhật domain; `dataset_ids` thay thế toàn bộ membership hiện tại. |
| DELETE | `/domains/{domain_id}` | Xóa domain và các membership. |
| PUT | `/datasets/{dataset_id}/layer` | Gán `layer_id`; truyền `null` để gỡ gán. |
| GET | `/databases/{database_id}` | Đọc business model tổng hợp cho database Superset. |
| PUT | `/databases/{database_id}/canvas` | Lưu JSON `layout` của business canvas; tối đa 1 MB. |

`LayerIn` nhận `name` (1–255 ký tự), `description` (tối đa 2.000), `color` theo dạng `#RRGGBB`, `level` và `sort_order` không âm. Tên layer và domain là duy nhất. `DomainIn.dataset_ids` nhận tối đa 1.000 Superset dataset ID; mỗi ID phải tồn tại và người gọi phải có quyền sửa dataset đó. Dataset được thêm vào domain sẽ có bản ghi Data Dictionary nếu chưa có.

`GET /databases/{database_id}` trả `database_id`, `layers`, `domains`, các `datasets` truy cập được, `business_canvas` và `lineage`. Mỗi dataset gồm schema, tên bảng, tên hiển thị, loại bảng, layer và trạng thái đã phân loại. Phần lineage được đọc qua service của module `data_lineage`; module đó tiếp tục sở hữu lineage canvas, edges và transformations. API trả response theo JSON envelope chuẩn của extension.

Layer/domain/canvas do module `business_model` sở hữu. Mapping layer dùng Superset dataset ID; membership domain liên kết tới model `TableDictionary` do `data_dictionary` sở hữu. Migration nội bộ tạo các bảng cần thiết và không thay đổi bảng metadata lõi của Superset.
