# Expert Rule Management API

Resource `expert-rules` nằm dưới `/api/v1/extensions/text-to-bi/superset-text-to-bi/expert-rules`. Route yêu cầu phiên đăng nhập và quyền `read`/`write` của resource; service kiểm tra thêm quyền trên dataset. Request ghi cần CSRF token. Duyệt/thu hồi cần quyền reviewer/Steward hoặc Admin; xóa rule có revision đang phục vụ cũng cần quyền review.

| Method và path | Quyền bổ sung | Request và kết quả |
| --- | --- | --- |
| `GET /datasets/<dataset_id>` | `require_view`, quyền đọc dataset | Trả `{rules}` gồm các rule trên dataset. |
| `GET /datasets/<dataset_id>/discovery` | `require_view`, quyền đọc dataset | Trả `{rules}` đã duyệt và còn hiệu lực theo các link. |
| `GET /datasets/<dataset_id>/options` | `require_view`, quyền đọc dataset | Trả `{options}` gồm dữ liệu lựa chọn cần thiết để biên soạn rule, như thuật ngữ và metric khả dụng. |
| `GET /<rule_uuid>` | `require_view`, quyền đọc dataset sở hữu rule | Trả `{rule}`. |
| `GET /<rule_uuid>/revisions` | `require_view`, quyền đọc dataset sở hữu rule | Trả `{revisions}` mới nhất trước. |
| `POST /` | Quyền sửa dataset | Body `RuleCreate`; tạo rule cùng revision nháp đầu tiên, trả `{rule}` với 201. |
| `PUT /<rule_uuid>` | Quyền sửa dataset | Body `RuleUpdate`; cập nhật nội dung thành revision mới theo `expected_revision`. |
| `POST /<rule_uuid>/approve` | Reviewer/Steward hoặc Admin | Body `{expected_revision}`; duyệt revision nháp hiện tại. |
| `POST /<rule_uuid>/revoke` | Reviewer/Steward hoặc Admin | Body `{expected_revision}`; thu hồi revision đang được phục vụ bằng revision mới. |
| `DELETE /<rule_uuid>` | Quyền sửa dataset; nếu rule đang được phục vụ cần quyền review | Xóa rule; trả thông báo xác nhận. |

`RuleCreate` yêu cầu `dataset_id`, `name` và nội dung rule. Nội dung cần 1–50 `conditions`, 1–50 `glossary_term_ids`; `exceptions`, `examples`, `metric_refs` tùy chọn (mỗi mảng tối đa 50). Tên tối đa 255 ký tự; mô tả tối đa 10.000 ký tự; domain tối đa 50 UUID. Condition có `column_name`, toán tử được liệt kê trong schema (`equals`, `contains`, so sánh, tập hợp, null…), `value_type` (`string`, `number`, `boolean`, `null`, `array`) và `value`; validator buộc kiểu giá trị phù hợp với toán tử. Metric reference gồm `kind` (`metric`, `superset_metric`) và `target_key`. `RuleUpdate` thêm `expected_revision` (>=1). Rule cần link tới thuật ngữ hợp lệ trên dataset; link metric được xác thực qua Metric Management.

Discovery chỉ đưa ra rule có revision được duyệt, còn khớp nội dung/link hiện hành. Glossary terms và manual/native metrics được đọc qua service của các module sở hữu chúng; dataset, cột và quyền truy cập dùng API/model Superset hiện có. Expert Rule lưu nội dung, revision và link của mình, không tạo bản sao model Superset.
