# Review Semantic Layer sau refactor — 12/11/2026

## Kết luận

Semantic Layer đã có ranh giới nghiệp vụ và luồng chạy cụ thể, đủ nền tảng cho MVP metadata có kiểm duyệt trên stack
hiện tại. Chưa thể kết luận hoàn chỉnh hoặc sẵn sàng phát hành: toàn bộ regression suite đang lỗi collection và còn
những khoảng trống về đồng thời, transaction và mức cưỡng chế ngữ nghĩa. Việc chuyển registry/public query đã triển
khai; các tồn đọng bên dưới chưa được sửa trong đợt chuyển này.

Đánh giá dựa trên source hiện có, test và Superset 6.1 chạy local. Không có load test, stress test hai request quản
trị đồng thời hoặc nghiệm thu đầy đủ bằng tài khoản Viewer/Query trong lượt review này.

## Những phần đã concrete

| Phần | Hành vi đã có |
| --- | --- |
| Data Dictionary | Metadata dataset/cột, grain, thời gian, vai trò, PII, lineage khai báo, file và AutoFill |
| Relationships | Đề xuất, kiểm tra dữ liệu, duyệt/thu hồi; consumer chỉ nhận contract và verification hiện hành đạt kiểm tra |
| Metrics | Định nghĩa nghiệp vụ, công thức giới hạn, defaults, hash phát hiện thay đổi, duyệt/thu hồi, ChartData/RLS |
| Glossary và Expert Rules | Revision, vòng đời duyệt, kiểm tra liên kết, nhóm, discovery và phát hiện mâu thuẫn |
| Business Model và Access Control | Phân tầng/nghiệp vụ, canvas/lineage, quyền Viewer/Query trên quyền dataset Superset |
| Ranh giới extension | Semantic Layer giữ metadata và quy tắc hợp lệ; AI Agent ghép catalog/graph/sources và sở hữu Ladder |
| Public API | Success envelope v1, adapter kiểm version/dạng/ID, lỗi HTTP an toàn; API quản trị và SSE giữ giao thức cũ |

`registry.py` ở gốc Semantic Layer ghép route và trang. Semantic Layer không còn source module `catalog`,
`semantic_query` hoặc `agent_ladder`. Thực thi metric và giới hạn truy vấn vẫn thuộc Metrics; không phụ thuộc Python
nội bộ của AI Agent. Hai extension giao tiếp qua HTTP với session của người dùng.

Hợp đồng public và danh sách URL: [public-api-v1.md](../specs/public-api-v1.md).

## Tồn đọng ưu tiên

### P1 — Regression gate chưa chạy được toàn bộ

`uv run scripts/check.py` qua Ruff và TypeScript nhưng pytest dừng ở **19 lỗi collection**. Test cũ còn import các
đường dẫn đã đổi, như `data_dictionary.services.column_semantics`, `modules.glossary`, `modules.expert_rules` và
`modules.semantic_query`. Đây là trạng thái kiểm chứng chưa hoàn chỉnh; không phải bằng chứng 19 lỗi runtime.

Cần chuyển test theo chủ sở hữu nghiệp vụ mới, sửa harness AST theo service/route hiện hành và đưa các test ghép
catalog còn lại sang AI Agent. Giữ các khẳng định nghiệp vụ, không thêm shim production hoặc bỏ test chỉ để có màu
xanh. Điều kiện đóng: toàn bộ `scripts/check.py` và suite AI Agent chạy qua.

### P1 — Chưa chứng minh an toàn khi sửa quan hệ đồng thời

`RelationshipContractRepository.read_by_from_column` đọc bình thường; các thao tác apply/approve/verify/revoke đọc
rồi sửa, chưa có khóa dòng hoặc version đối chiếu để chặn stale write xuyên các request. Kiểm tra thay target đã
chặn trường hợp tuần tự, nhưng chưa chứng minh được trường hợp hai admin cùng thao tác.

Đây là rủi ro suy ra từ code, chưa tái hiện bằng stress test. Cần chọn khóa/version nhất quán cho cả contract và
metadata hai đầu, rồi test trên PostgreSQL với transaction độc lập. Khóa AutoFill xuyên worker đã có không bao phủ
vòng đời relationship.

### P2 — Transaction có ngoại lệ, chưa bảo đảm nguyên tử toàn luồng

`seed_dictionary` tự commit theo ngoại lệ đã ghi trong handbook; một số lệnh ghi gọi seed trước khi cập nhật nghiệp
vụ. Luồng tạo dataset còn đi qua `CreateDatasetCommand` của Superset và transaction riêng giữa hai extension.
Rollback cuối route không thể hoàn tác các commit đã xảy ra trước đó.

Luồng đề xuất đã có `creation_key`, hash nội dung và cờ hoàn tất để thử lại. Cần fault-injection ở các điểm tạo
dataset/metric/metadata và xác nhận retry không trùng, không để dataset dang dở được dùng như đã hoàn tất.

### P2 — Metadata ngữ nghĩa chưa đồng nghĩa với cưỡng chế toàn bộ

`metric_contract_ineligibility` kiểm tên, grammar, cột tồn tại/active/vật lý. Hàm này chưa dùng `semantic_role`, danh
sách `aggregations` hoặc đơn vị của Data Dictionary để chứng minh phép tính hợp lệ về nghiệp vụ. Hiện các trường đó
còn là ngữ cảnh cho người soạn và Agent, với người duyệt chịu trách nhiệm về ý nghĩa metric.

Muốn coi Semantic Layer là bộ kiểm chứng ngữ nghĩa đầy đủ cần định nghĩa rõ phép tổng hợp theo role, tính cộng được
theo grain và đơn vị, rồi kiểm chúng trong vòng đời contract. Không nên mở rộng grammar trước khi có quy tắc này.

## Giới hạn cần hiểu đúng

- Verification quan hệ đạt khi đích duy nhất, có giá trị và kiểu tương thích. Orphan được báo nhưng không chặn duyệt;
  đây là chính sách hiện tại trong `verification_result`, không phải cam kết inner join không mất dòng.
- Hash bảo vệ thay đổi metadata; verification không có TTL hay kiểm tra liên tục chất lượng dữ liệu. Dữ liệu nguồn
  thay đổi sau khi duyệt vẫn cần recheck.
- `contains_pii` là nhãn, chưa phải cơ chế masking. Transformation khai báo phục vụ lineage, không thực thi ETL.
- Thực thi metric hiện hỗ trợ phạm vi grammar và truy vấn một dataset đã quy định. Schema linking đa bảng thuộc AI
  Agent; sự có mặt của graph chưa chứng minh luồng chat tự join đã nghiệm thu đầy đủ.
- JSON Schema public hiện mô tả envelope; kiểm DTO chi tiết nằm trong adapter và test. Chưa có schema/OpenAPI tự sinh
  đầy đủ cho mọi payload. Chưa đo tải hoặc benchmark N+1 trên catalog lớn.

## Bằng chứng kiểm tra và triển khai

| Kiểm tra | Kết quả |
| --- | --- |
| Ruff backend hai extension | Qua |
| TypeScript hai frontend | Qua |
| Toàn bộ AI Agent tests và nhóm public metadata/draft/dictionary/AutoFill/expert-rule regression | 239 passed |
| Toàn bộ Semantic Layer qua `scripts/check.py` | Chặn bởi 19 lỗi import khi collection |
| Compile/import bằng Python 3.10.21 trong Superset | Qua: 195 module Semantic Layer, 119 module AI Agent |
| Smoke sau triển khai | 17 GET endpoint trả 200; public endpoint đúng envelope v1 |
| Đọc trang và dimension members | `/semantic-layer/` và members dataset có metric đã duyệt trả 200 |
| Input sai và anonymous | database_id văn bản trả 400 ở dictionary/graph; catalog anonymous trả 401 |
| So sánh trước/sau | Catalog 9 dataset, graph 8 bảng, sources 16 dataset giữ nguyên nội dung; graph đổi thứ tự bảng |
| Bundle | Đã build, copy cả hai bundle, restart; SHA-256 host trùng bundle đang triển khai |

Smoke và so sánh dùng admin, dữ liệu local hiện có, không gọi LLM hoặc tạo dữ liệu nghiệp vụ để test. Thứ tự bảng
graph được chuẩn hóa theo dataset_id khi đối chiếu; không coi thứ tự đó là hợp đồng nghiệp vụ.

Mốc hoàn tất tiếp theo nên là regression suite xanh và lifecycle relationship có kiểm thử đồng thời. Trước hai mốc
này, đánh giá phù hợp là **MVP có nghiệp vụ rõ ràng, đang ổn định sau refactor**, chưa phải Semantic Layer hoàn chỉnh.
