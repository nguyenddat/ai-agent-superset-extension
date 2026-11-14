# Chuyển Agent Ladder sang extension AI Agent

AI Agent sở hữu luồng đề xuất dataset, dữ liệu đề xuất và việc xét duyệt. Semantic Layer sở hữu metadata và các kiểm
tra khi tạo dataset, metric. Hai extension gọi nhau qua HTTP bằng cookie và CSRF token của người dùng; không import
model, repository hoặc service Python nội bộ của nhau.

## Quyền sở hữu

- `ai-agents/.../modules/agent_ladder/`: `DatasetProposal`, repository, service và API xét duyệt.
- `ensure_agent_tables()` tạo bảng `text_to_bi_dataset_proposal` nếu chưa tồn tại. Tên bảng, cột, khóa ngoại và ID giữ
  nguyên; không sao chép, đổi tên hay xóa dữ liệu khi chuyển. Semantic Layer không còn tạo bảng này.
- Frontend "Xử lý câu hỏi" → "Đề xuất dataset" vẫn ở Semantic Layer, gọi API AI Agent như các trang câu hỏi và cách
  hiểu của người dùng.
- Semantic Layer không còn module `agent_ladder` hoặc `semantic_query`. Các thao tác kiểm tra metadata thuộc
  `data_dictionary` và `metric_management`; AI Agent sở hữu việc ghép catalog, schema graph và nguồn đề xuất.

## API

Tiền tố Semantic Layer là `/extensions/text-to-bi/superset-semantic-layer/semantic-layer`.
Tiền tố Agent Ladder mới là `/extensions/text-to-bi/superset-ai-agent/agent-ladder`.
Tiền tố Semantic Query là `/extensions/text-to-bi/superset-ai-agent/semantic-query`.
Response public thành công dùng `{"schema_version": 1, "result": {...}}`; xem [public-api-v1.md](public-api-v1.md).

| Chức năng | API mới | Quyền |
| --- | --- | --- |
| Đọc dataset nguồn | AI Agent Semantic Query `GET /data-model/sources` | Semantic Layer Query, lọc quyền dataset |
| Tạo hoặc dùng lại metric nháp | Semantic Layer `POST /metric-candidates` | Semantic Layer Query, quyền dataset, CSRF |
| Kiểm tra dataset nháp | Semantic Layer `POST /dataset-drafts/validate` | Semantic Layer Query, quyền dataset nguồn, CSRF |
| Tạo dataset đã xét duyệt | Semantic Layer `POST /dataset-drafts/create` | Admin, CSRF |
| Gửi đề xuất | AI Agent `POST /dataset-proposals` | Semantic Layer Query, CSRF |
| Danh sách đề xuất | AI Agent `GET /dataset-proposals` | Admin |
| Sửa đề xuất chờ xử lý | AI Agent `PUT /dataset-proposals/<id>` | Admin, CSRF |
| Từ chối | AI Agent `POST /dataset-proposals/<id>/reject` | Admin, CSRF, lý do không rỗng và tối đa 512 ký tự |
| Tạo từ đề xuất | AI Agent `POST /dataset-proposals/<id>/create` | Admin, CSRF |

Các URL cũ `/agent-sources`, `/agent-metrics`, `/agent-dataset-proposals` và `/dataset-proposals` trong API Semantic
Layer được thay bằng các URL trên. Phải cập nhật và triển khai cả hai bundle cùng nhau. Các contract kiểm tra công
thức, tái sử dụng metric cùng công thức và đánh dấu kết quả tạm tính vẫn do Semantic Layer thực hiện.

## Transaction và thử lại

AI Agent khóa dòng đề xuất trước khi sửa, từ chối hoặc tạo; chỉ đề xuất `pending` được xử lý. Duyệt tạo gọi Semantic
Layer trước rồi mới ghi `status=created`, `dataset_id`, người duyệt và thời điểm. Nếu HTTP thất bại, đề xuất vẫn chờ.
Tác giả metric được giữ theo người đề xuất ban đầu, không đổi thành người duyệt.

Hai extension có transaction riêng, không có commit nguyên tử xuyên HTTP. AI Agent gửi khóa ổn định
`ai-agent:dataset-proposal:<id>`. Semantic Layer lưu khóa, hash nội dung và cờ hoàn tất trong `dataset.extra`:

- Cùng khóa và nội dung, đã hoàn tất: trả dataset đã tạo, không tạo thêm metric.
- Cùng khóa nhưng nội dung khác: từ chối để tránh gán một dataset khác nội dung cho đề xuất.
- Dataset đã tạo nhưng metadata chưa hoàn tất: tiếp tục hoàn thiện dictionary, khóa cột, lineage và metric trên
  dataset đó. Cờ hoàn tất được lưu cùng commit cuối của metadata.

Việc tạo dataset dùng command của Superset và `seed_dictionary`, vốn có commit nội bộ; có thể tồn tại dataset đang
hoàn thiện sau lỗi. Cơ chế khóa tạo cho phép thử lại bước đó; không tuyên bố rollback toàn bộ hai extension trong một transaction.

## Kiểm chứng

- Test AI Agent kiểm tra đề xuất trùng SQL, trạng thái đã xử lý, giữ câu hỏi gốc, giữ người đề xuất, khóa thử lại ổn
  định và không chuyển trạng thái khi HTTP lỗi.
- Test Semantic Layer kiểm tra SQL, công thức, suy khóa cột và nhận lại dataset đã tạo theo cùng khóa/nội dung.
- Compile/import hai backend trong Superset Python 3.10; kiểm tra cả hai bundle và các API mới sau triển khai.

Kết quả ngày 2026-11-12: 180 test liên quan đạt; hai backend compile/import được trong Superset Python 3.10, hai
bundle build và triển khai thành công. Hai GET mới trả 200; body sai ở API kiểm tra draft/metric trả 400; gửi đề xuất
thiếu CSRF trả 403; 13 endpoint smoke hiện có trả 200. Chưa thử tạo dataset thật qua HTTP. Bộ test Semantic Layer
đầy đủ vẫn còn lỗi import từ đợt refactor module trước đó, không coi toàn bộ suite đã đạt.
