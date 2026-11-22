# Glossary Management API

Resource `glossary` nằm dưới `/api/v1/extensions/text-to-bi/superset-text-to-bi/glossary`. Mọi route cần phiên đăng nhập và quyền `read`/`write` của resource. Các thao tác ghi cần CSRF token; service còn kiểm tra quyền xem/sửa dataset và quyền review cho duyệt/thu hồi hoặc xóa thuật ngữ đang được phục vụ.

| Method và path | Quyền bổ sung | Request và kết quả |
| --- | --- | --- |
| `GET /datasets/<dataset_id>` | `require_view`, quyền đọc dataset | Trả `{terms}` gồm thuật ngữ của dataset. |
| `GET /datasets/<dataset_id>/discovery` | `require_view`, quyền đọc dataset | Trả `{terms}` chỉ gồm revision đã duyệt, với các link còn hợp lệ. |
| `GET /<term_uuid>` | `require_view`, quyền đọc dataset sở hữu thuật ngữ | Trả `{term}`. |
| `GET /<term_uuid>/revisions` | `require_view`, quyền đọc dataset sở hữu thuật ngữ | Trả `{revisions}` theo thứ tự revision mới nhất trước. |
| `POST /` | Quyền sửa dataset | Body `GlossaryCreate`; tạo thuật ngữ và revision nháp số 1, trả `{term}` với 201. |
| `PUT /<term_uuid>` | Quyền sửa dataset | Body `GlossaryUpdate`; tạo revision nháp mới khi nội dung/link đổi hoặc revision hiện tại đã bị thu hồi. |
| `POST /<term_uuid>/approve` | Reviewer/Steward hoặc Admin | Body `{expected_revision}`; duyệt đúng revision nháp hiện tại. |
| `POST /<term_uuid>/revoke` | Reviewer/Steward hoặc Admin | Body `{expected_revision}`; tạo revision thu hồi từ nội dung revision đang được phục vụ. |
| `DELETE /<term_uuid>` | Quyền sửa dataset; nếu thuật ngữ có revision được phục vụ cần quyền review | Xóa thuật ngữ; trả thông báo xác nhận. |

`GlossaryCreate` cần `dataset_id`, `canonical_name`, `definition`; có thể gửi `synonyms` (tối đa 50), `links` (tối đa 100) và `business_domain_ids` (tối đa 50 UUID). `GlossaryUpdate` nhận nội dung/synonyms/links, `expected_revision` từ 1 trở lên và danh sách domain. Link gồm `kind` (`table`, `column`, `metric`, `superset_metric`) và `target_key`. Tên được chuẩn hóa khoảng trắng và duy nhất không phân biệt hoa thường trong dataset. Revision kiểm tra số kỳ vọng để tránh ghi đè cập nhật đồng thời.

Response ghi/read dùng envelope theo key `term` hoặc `revisions`; discovery trả `terms` với tên, định nghĩa, synonyms, business domains và link còn sống. Dataset/cột/metric và quyền truy cập được lấy từ các model/service Superset, Data Dictionary và Metric Management đang sở hữu chúng. Glossary chỉ lưu liên kết nghiệp vụ; discovery bỏ qua link tới đối tượng Superset không còn tồn tại/không còn thuộc dataset.
