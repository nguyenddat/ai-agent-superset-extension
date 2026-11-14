# Public API v1 giữa Semantic Layer và AI Agent

## Ranh giới

Semantic Layer giữ metadata, quy tắc hợp lệ và quyền truy cập tại các module nghiệp vụ. `registry.py` ở gốc extension
chỉ ghép `SemanticLayerAPI` và đăng ký trang, thay cho module `catalog`. Không còn module `semantic_query` tại Semantic
Layer. AI Agent sở hữu module `semantic_query`, ghép catalog/schema graph/sources và đọc giá trị qua ChartData.

Các GET quản trị hiện có phục vụ Admin/Viewer; các projection public bên dưới phục vụ quyền Semantic Layer Query,
không mở rộng quyền của GET quản trị. Mỗi projection chỉ công bố dữ liệu thuộc module sở hữu nó, không ghép tri thức
xuyên module. Hai extension trao đổi qua HTTP; không import mã Python nội bộ của nhau.

## Envelope

Mọi response thành công của các API public trong danh sách này dùng cùng dạng:

```json
{"schema_version": 1, "result": {"datasets": []}}
```

`result` luôn là object; danh sách có tên trường rõ ràng, không trả array ở gốc. ID là số nguyên, không nhận bool;
giá trị không có là null; cờ là boolean; danh sách rỗng là `[]`. Các trường có cùng ý nghĩa dùng cùng tên trong cùng
projection. Thêm trường tùy chọn trong result được phép; thay đổi phá hợp đồng cần schema_version mới. Schema envelope
máy đọc ở [public-api-v1.schema.json](public-api-v1.schema.json).

Lỗi tuân theo handbook chung: HTTP status 4xx/5xx và JSON `message` an toàn cho người dùng; response lỗi không phải
success envelope. Adapter giữ status 400/401/403/404/409/429 khi gọi public API, trả 503 khi nguồn không sẵn sàng hoặc
response không đúng schema. Phiên bản thiếu, khác 1, bool thay số, result sai dạng hoặc định danh trùng đều bị từ chối.

Đây là hợp đồng của API public phục vụ tích hợp. Các API quản trị và SSE chat giữ giao thức đang dùng; helper frontend
giải bọc v1 và tiếp tục đọc response quản trị cũ. Không thay response của API Superset gốc.

## Semantic Layer: projection theo module

Tiền tố: `/extensions/text-to-bi/superset-semantic-layer/semantic-layer`.

| API | Module | result |
| --- | --- | --- |
| GET `/datasets/query-metadata?database_id=<id>` | Data Dictionary | `datasets`, `database` (null khi không lọc database) |
| GET `/relationships/approved` | Data Dictionary | `relationships` đã duyệt, hash và verification còn khớp, kiểm tra đạt |
| GET `/metrics/query-metadata` | Metrics | `metrics`, `limits.max_rows` do server áp dụng |
| GET `/glossary/discovery` | Glossary | `terms` đã duyệt, liên kết còn hợp lệ |
| GET expert API `/expert-rules/discover` | Expert Rules | `rules` đã duyệt, còn hiện hành |
| POST `/metric-candidates` | Metrics | `metric`, `provisional` |
| POST `/dataset-drafts/validate` | Data Dictionary | `draft` đã chuẩn hóa |
| POST `/dataset-drafts/create` | Data Dictionary | `dataset_id`; Admin, giữ cơ chế thử lại theo creation_key |
| POST `/dataset/<id>/metrics/<id>/semantic-query/execute` | Metrics | dữ liệu truy vấn, defaults đã áp dụng, trạng thái tạm tính |

Dataset projection có `id`, `name`, `schema`, `is_virtual`, `row_level_security`, `database` (`id`, `name`, `dialect`),
`dictionary`, `dictionary_columns`, `columns` Superset, `grains`, `layer`. Không có URI kết nối hoặc SQL của dataset;
expression cột có thể xuất hiện để xác định cột nhãn của chính dataset người gọi được đọc. Tham chiếu cột chỉ công bố
đích thuộc dataset người gọi được đọc. Snapshot không seed hay ghi metadata.

Metric projection có `dataset_id`, `metric_id`, `metric_name`, `label`, `expression`, `description`, `d3format`,
`state`, `origin`, `definition`, `unit`, `steward_name`, `query_defaults`. Server tính state từ contract và công thức/
defaults hiện tại. Catalog chỉ lấy state approved; nguồn tạo metric có thể dùng các công thức đã lưu để tham khảo.

Relationship projection có `id`, `from_dataset_id`, `from_column`, `to_dataset_id`, `to_column`, `cardinality`.
Chỉ công bố khi cả hai dataset được đọc, contract approved và verification hiện tại đạt.

## AI Agent: ghép dữ liệu cho Agent

Tiền tố: `/extensions/text-to-bi/superset-ai-agent/semantic-query`.

| GET | result |
| --- | --- |
| `/semantic-catalog` | `datasets`, `relationships`, `limits` |
| `/schema-graph?database_id=<id>` | `version` của graph, `database`, `tables`, `edges`, `excluded` |
| `/data-model/sources` | `datasets` loại aggregate/base, cột, công thức tham khảo và mã dữ liệu |
| `/dataset/<id>/dimension-members` | `dataset_id`, `dimensions`, `time_ranges` |

Tất cả yêu cầu quyền Semantic Layer Query. Metadata được đọc qua adapter HTTP bằng cookie người gọi. Giá trị mã,
dimension và khoảng thời gian được truy vấn qua Superset ChartData với `validate()` và RLS của chính người gọi.
Graph loại dataset có RLS và các cạnh liên quan; catalog không đưa metric chưa được duyệt vào kết quả. Các hàm hash,
duyệt, kiểm tra SQL và thực thi metric tiếp tục nằm trong module Semantic Layer sở hữu nghiệp vụ đó.

API `/extensions/text-to-bi/superset-ai-agent/agent-ladder/dataset-proposals` cùng các thao tác sửa/từ chối/tạo cũng
dùng envelope v1: result chứa `proposals` hoặc `proposal`. Phân quyền và trạng thái đề xuất giữ như đặc tả Agent Ladder.

## Chuyển đổi

Các URL `/semantic-catalog`, `/schema-graph`, `/data-model/sources`, `/dataset/<id>/dimension-members` cũ ở Semantic
Layer được bỏ; caller chuyển sang AI Agent. Các response public cũ không có envelope được thay bằng v1. Phải triển
khai cả hai bundle cùng nhau. Giới hạn thực thi metric và latest-data lookup vẫn ở Metrics, không phụ thuộc AI Agent.

Kiểm thử gồm schema sai phiên bản/dạng, metadata sai ID, metric chưa duyệt, RLS và quyền đọc hai đầu quan hệ; so sánh
catalog/schema graph/sources trên stack trước và sau chuyển để kiểm tra dữ liệu nghiệp vụ được giữ nguyên.
