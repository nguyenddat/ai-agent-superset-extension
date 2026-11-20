# Kiến trúc backend

Mô tả backend Semantic Layer: `extensions/semantic-layer/backend/src/text_to_bi/superset_semantic_layer/`. Backend AI
Agent (`extensions/ai-agents/backend/src/text_to_bi/superset_ai_agent/`) theo cùng các lớp và cấu trúc module; chỗ khác
nằm ở mục [Backend AI Agent](#backend-ai-agent).

## Các lớp

```text
entrypoint.py, registry.py, migrations.py       ← ghép ứng dụng: đăng ký API, tạo bảng
modules/<nghiệp vụ>                             ← models, repositories, services, routes của từng nghiệp vụ
core                                            ← hạ tầng dùng chung: cấu hình, bảo mật, xử lý lỗi của route
common                                          ← nền tảng thuần: BaseModel, BaseRepository, exception gốc, formatter,
                                                  schema dùng chung (ReviewStatus); không phải một module
```

Mũi tên phụ thuộc chỉ đi xuống:

| Lớp | Được import | Không được import |
| --- | --- | --- |
| `common` | thư viện ngoài | `core`, `modules`, `migrations` |
| `core` | `common` | `modules`, `migrations` |
| `modules/<x>` | `common`, `core`, service / repository / model / exception của module khác | routes của module khác |
| `migrations.py`, `registry.py`, `entrypoint.py` | mọi thứ ở trên | — |

- `core/config.py`: lớp `Settings` đọc biến môi trường.
- `core/security.py`: quyền admin, quyền đọc dataset, CSRF, quy tắc người duyệt thứ hai.
- `core/database.py`: `handle_errors` và `rollback_on_error` (xem [hanh-vi.md](hanh-vi.md)).
- `core/exceptions.py`: lỗi của các kiểm tra dùng chung (admin, quyền dataset, CSRF, thân request).
- `core/llm.py`: model chat OpenRouter của AI AutoFill và của bộ chấm mâu thuẫn.
- `migrations.py`: tạo và nâng cấp bảng của mọi module, một lần cho mỗi process (`ensure_dictionary_tables`). Nó nằm
  trên các module vì cần model của tất cả.
- `registry.py`: file ở gốc extension Semantic Layer, ghép `SemanticLayerAPI` từ route mixin và đăng ký
  `SemanticLayerView`. Registry là lớp ghép ứng dụng, không phải module nghiệp vụ.

## Module chia theo nghiệp vụ

Một module là một nghiệp vụ, không phải một model hay một bảng. Một nghiệp vụ có thể có nhiều model; một model chỉ
thuộc một nghiệp vụ.

| Module | Nghiệp vụ |
| --- | --- |
| `data_dictionary` | Từ điển dataset và cột, grain, đánh dấu dữ liệu cá nhân (PII), biến đổi cột do quản trị viên khai báo, nhập/xuất file Excel, AI AutoFill (prompt trong `prompts/`); quan hệ giữa các bảng: gợi ý, kiểm tra dữ liệu và relationship contract |
| `business_model` | Tầng dữ liệu, nghiệp vụ, canvas và lineage |
| `metric_management` | Gốc metric: định nghĩa nghiệp vụ, giá trị mặc định khi truy vấn, metric contract và vòng đời duyệt, lịch sử, chạy metric |
| `glossary_management` | Thuật ngữ nghiệp vụ, nhóm thuật ngữ cùng nghĩa, vòng đời duyệt, khám phá thuật ngữ, import/export file; embedding và gợi ý gom nhóm (dùng chung với expert rule); phát hiện mâu thuẫn giữa thuật ngữ, rule và metric |
| `expert_rule_management` | Expert rule, nhóm rule tương đồng, vòng đời duyệt, khám phá rule, import/export file (API riêng `ExpertRuleAPI`) |
| `access_control` | Nhóm quyền Superset xem và truy vấn Semantic Layer, màn gán nhóm quyền cho người dùng |
| `superset` | Dataset, database, người dùng và nhóm quyền của Superset: không có bảng riêng |

Thêm tính năng: đặt vào module của nghiệp vụ đó. Chỉ tạo module mới khi có một nghiệp vụ mới, có ngôn ngữ và vòng đời
riêng. Không tạo module chỉ để chứa một model, một bảng hay một kiểu tiện ích.

Mọi truy vấn vào bảng của Superset (`SqlaTable`, `Database`, người dùng) đi qua module `superset`:
`modules/superset/services/srv_dataset.py` (`get_dataset`, `require_dataset`, `datasets_on_database`, …) và
`services/srv_user.py` (`active_users`, `user_names`, `require_user`); nhóm quyền và permission FAB đi qua
`services/srv_role.py` (`ensure_role`, `revoke_permissions`, `replace_user_roles`) bằng security manager. Không gọi `db.session.query(SqlaTable)` ở module khác. Truy vấn
join bảng của một module với bảng Superset (ví dụ dataset dictionary với `SqlaTable`) nằm trong repository của module đó.

## Cấu trúc một module

```text
modules/<module>/
├── models/model_*.py        # bảng của module trong metadata database, cột khai báo `Mapped[...]`; __init__.py liệt kê __all__
├── repositories/repo_*.py   # một repository cho mỗi model, kế thừa BaseRepository: mọi truy vấn của module
├── dependencies.py          # hàm tạo repository gắn với db.session của request
├── exceptions.py            # lỗi của module, kế thừa common/exceptions
├── schemas/                 # enum và kiểu dữ liệu riêng của module (nếu có)
├── services/srv_*.py        # quy tắc nghiệp vụ và các hàm module khác gọi; không đọc request
├── utils/util_serializer.py # mọi hàm chuyển model thành JSON của module, gộp một file
└── routes/route_*.py        # route mixin kế thừa `core.routing.RouteMixin`: đọc request, gọi service, trả response
```

- **Tên method** theo CRUD: `create`, `read` / `read_*`, `update`, `delete`; trong repository và service chia mục bằng
  comment `# -------------------------READ---------------------------`. Service nghiệp vụ chính là một lớp
  (`MetricDefService`, `GlossaryTermService`, `ExpertRuleService`), hàm phụ trợ để ở mức module.
- **Không viết docstring** cho module, class và hàm (xem [quy-uoc-code.md](quy-uoc-code.md#docstring-và-comment)).
- **Import**: trong cùng module dùng import tương đối; ngoài module (`common`, `core`, module khác) dùng đường dẫn đầy đủ
  `text_to_bi.superset_semantic_layer...`.
- **Repository** là nơi duy nhất viết truy vấn. Service và route gọi repository qua `dependencies.py`.
- **Service** không đọc `request`. Cần dữ liệu từ request thì route đọc rồi truyền vào
  (`review_reason(request.get_json(silent=True))`).
- **Route mixin** chỉ gọi method của chính mixin đó qua `self`. Một helper mà mixin hay module khác cũng cần thì để thành
  hàm trong `services/` của module sở hữu nghiệp vụ, và nơi dùng import nó, ví dụ `contract_is_approved_current` trong
  `metric_management/services/srv_metric_contract.py` hay `discoverable_glossary_terms` trong
  `glossary_management/services/srv_glossary_link.py`.
  `SemanticLayerAPI` ghép các mixin, nhưng không mixin nào được dựa vào method của mixin khác.
- **Gọi giữa các module** đi qua service, repository factory, model hoặc exception của module kia, không đi qua route.

## Backend AI Agent

Cùng các lớp `common`, `core`, `modules` và cùng cấu trúc một module. Khác Semantic Layer ở mấy điểm:

- Không có module ghép route: mỗi module có lớp `RestApi` riêng trong `routes/`, và `entrypoint.py` import chúng.
- Lớp lỗi gốc là `AgentError` (`common/exceptions/`); chỉ có `ValidationError`, `NotAuthorizedError`,
  `NotFoundError` và `ServiceUnavailableError` vì AI Agent không có vòng đời duyệt.
- `migrations.py` có `ensure_agent_tables()`, tạo bảng của `sessions`, `questions`, `definitions`.

| Module | Nghiệp vụ |
| --- | --- |
| `chat` | Trả lời một câu hỏi: pipeline, prompt, lập kế hoạch truy vấn, diễn giải công thức, `/chat/stream` |
| `sessions` | Cuộc trò chuyện của người dùng và trang `/ai-agent/` |
| `questions` | Nhật ký câu hỏi và cách quản trị viên xử lý câu `needs_review` |
| `definitions` | Cách hiểu của người dùng, điều kiện suy ra từ đó, và màn duyệt của quản trị viên |
| `schema_link` | Đường join và SQL trên base table, phòng thử phân tích của quản trị viên |
| `semantic_query` | Ghép metadata public của các module Semantic Layer thành catalog, schema graph và nguồn dữ liệu cho Agent; đọc giá trị dimension, mã và khoảng thời gian qua Superset ChartData với quyền người gọi |
| `agent_ladder` | Đề xuất dataset của AI Agent: lưu đề xuất, giới hạn số bản chờ, sửa, từ chối và điều phối tạo dataset qua HTTP tới Semantic Layer |
| `semantic_layer` | Đọc và gọi Semantic Layer qua HTTP với cookie của người dùng: catalog, data model, chạy metric; không có bảng |
| `superset` | Dashboard, người dùng và truy vấn ChartData của Superset: chỉ đọc, không có bảng riêng |

- Mọi lời gọi HTTP sang Semantic Layer đi qua `modules/semantic_layer/services/`; module khác không tự gọi `requests`.
- Semantic Layer không sở hữu module `catalog`, `semantic_query`, `agent_ladder` hay bảng đề xuất. Mỗi module nghiệp
  vụ cung cấp metadata của mình: Data Dictionary có `/datasets/query-metadata`, `/relationships/approved`; Metrics
  có `/metrics/query-metadata`; Glossary/Expert Rule có API discovery đã duyệt. AI Agent gọi qua HTTP rồi ghép dữ liệu.
- Semantic Layer cung cấp `POST /metric-candidates` (`metric_management`), `POST /dataset-drafts/validate` và
  `POST /dataset-drafts/create` (`data_dictionary`). Các API này kiểm tra quyền dataset, SQL và metric tại nơi sở hữu metadata.
- API public dùng envelope `{"schema_version": 1, "result": {...}}`; adapter kiểm tra schema trước khi sử dụng.
  Xem [hợp đồng public v1](../specs/public-api-v1.md). Thực thi metric, kiểm tra công thức, trạng thái duyệt, hash và
  giới hạn truy vấn vẫn thuộc Metrics; helper latest-data và row cap nằm trong module đó.
- AI Agent sở hữu model `DatasetProposal` và migration của bảng `text_to_bi_dataset_proposal`; giữ nguyên tên bảng
  khi chuyển từ Semantic Layer để bảo toàn dữ liệu. Trang xét duyệt trong frontend Semantic Layer gọi API AI Agent,
  tương tự các trang nhật ký câu hỏi và cách hiểu người dùng.
- Tạo dataset qua HTTP và cập nhật đề xuất là hai transaction. AI Agent khóa đề xuất khi xử lý; Semantic Layer lưu
  khóa tạo, hash payload và cờ hoàn tất trong `dataset.extra`. Lần thử lại nhận dataset đã hoàn tất hoặc tiếp tục
  hoàn thiện metadata của dataset đó; từ chối nếu nội dung khác. Xem [đặc tả chuyển Agent Ladder](../specs/agent-ladder-trong-ai-agent.md).
- Test cục bộ không có Superset: service thuần (phân tích request, lập kế hoạch, pipeline) không import repository hay
  `superset`, để test import được.

## Superset 6.1 và Python 3.10

- Code chạy trong image Superset 6.1, Python 3.10, SQLAlchemy 1.4. Không dùng cú pháp mới hơn Python 3.10.
- Import nặng của Superset chỉ cần khi chạy (ví dụ `ChartDataCommand`) thì import trong hàm, để test cục bộ vẫn import
  được module.
- Sau khi sửa backend, chạy `uv run scripts/compat.py` để biên dịch và import mọi module trong container.
