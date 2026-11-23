# Kiến trúc

Mô tả extension `superset-text-to-bi` (`extensions/text-to-bi`, publisher `text-to-bi`). Backend nằm ở
`backend/src/text_to_bi/superset_text_to_bi/`, frontend ở `frontend/src/`. Extension là bản chuyển ứng dụng standalone
(Next.js/FastAPI, repository `ai-agent-superset-standalone`) vào Superset; hai extension cũ AI Agent và Semantic Layer
đã bị xóa khỏi repository.

## Superset làm host

```text
Trình duyệt ── Superset (gunicorn, http://localhost:8089) ── superset-db (PostgreSQL: metadata Superset + schema text_to_bi)
                 │  nạp superset-text-to-bi-0.1.0.supx        ├─ warehouse-db (dữ liệu nghiệp vụ, truy vấn qua SQL Lab)
                 │                                             ├─ qdrant (chỉ mục ngữ nghĩa Text2SQL)
                 │                                             └─ OpenRouter (mô hình chat, embedding)
superset-worker (Celery, broker redis) ── chạy job đồng bộ chỉ mục Qdrant
```

- `docker-compose.yml` chạy `superset`, `superset-worker`, `superset-init`, `superset-db`, `warehouse-db`, `redis`,
  `qdrant` và `airflow`. Image `text-to-bi-superset:6.1.0` dựng từ `simulation/superset/Dockerfile`, cài thêm các gói
  backend cần (LangChain, LangGraph, Presidio, spaCy, openpyxl…).
- Bundle `.supx` được chép vào volume `superset_extensions`, gắn ở `/app/superset_home/extensions/` của `superset` và
  `superset-worker` (`EXTENSIONS_PATH` trong `simulation/superset/superset_config.py`, cờ `ENABLE_EXTENSIONS`).
- Extension không có server riêng: mọi API là REST API của Flask-AppBuilder chạy trong process Superset, dùng session
  đăng nhập, security manager và `db.session` của Superset.

## Backend

### Các lớp

```text
entrypoint.py         ← Superset import khi nạp extension: đăng ký mọi API, trang /text-to-bi/, trigger ingestion,
                        task Celery; khai báo view menu của extension là admin-only
modules/<nghiệp vụ>   ← models, repositories, services, routes, migrations của từng nghiệp vụ
agent_package/        ← gọi mô hình ngôn ngữ: model chat, embedding, tool agent, prompt (prompts/)
core/                 ← hạ tầng route: cấu hình, xử lý lỗi, CSRF, đọc request, quyền class FAB
common/               ← nền tảng thuần: BaseModel, BaseRepository, exception gốc, formatter, biểu đồ (charts/)
```

| Lớp | Được import | Không được import |
| --- | --- | --- |
| `common` | thư viện ngoài, `superset` | `core`, `agent_package`, `modules` |
| `core` | `common` | `agent_package`, `modules` |
| `agent_package` | `common`, `core` | `modules` |
| `modules/<x>` | mọi lớp trên; service, repository, model, exception, migration của module khác | routes của module khác |
| `entrypoint.py` | mọi thứ | — |

- `core/config.py`: lớp `Settings` (pydantic-settings) đọc biến môi trường: OpenRouter, Qdrant, giới hạn Text2SQL.
- `core/routing.py`: `API_CLASS_PERMISSION = "text_to_bi_api"`, mọi API dùng chung permission class này;
  `error_response` trả `{code, message}`.
- `core/database.py`: `handle_errors`, `rollback_on_error`. `core/security.py`: `csrf_protected`.
  `core/validation.py`: `request_body(schema)` kiểm tra thân request bằng Pydantic, `query_int(...)`.
- `common/base_model.py`: mọi bảng của extension nằm trong schema PostgreSQL `text_to_bi` của database metadata
  Superset (`schema_table_args`), khóa chính UUID v7 (`common/utils/identifiers.py`), `created_at` / `updated_at` có
  timezone; `AuditedModel` thêm `created_by_fk` / `changed_by_fk` trỏ `ab_user.id`.
- `modules/management_payload.py` (`json_payload`) và `modules/management_domains.py` (`DomainAssignment`) là helper
  dùng chung của các module quản trị.

### Module chia theo nghiệp vụ

| Module | Prefix API | Nghiệp vụ |
| --- | --- | --- |
| `auth` | `/auth` | Người dùng hiện tại và quyền của họ, bốn nhóm quyền Text to BI, gán nhóm quyền; trang `/text-to-bi/` (`TextToBIView`) |
| `data_dictionary` | `/data-dictionary` | Mô tả bảng và cột của dataset Superset, vai trò cột, grain thời gian, từ đồng nghĩa, AI AutoFill |
| `business_model` | `/business-model` | Miền nghiệp vụ, tầng dữ liệu, gán dataset vào tầng, canvas của database |
| `data_lineage` | `/data-lineage` | Cạnh giữa các bảng, phép biến đổi đến từng cột, canvas lineage, xem trước SQL |
| `metric_management` | `/metrics` | Metric tự tạo (nháp, duyệt, thu hồi) và đọc metric có sẵn của Superset |
| `glossary_management` | `/glossary` | Thuật ngữ nghiệp vụ, revision, liên kết, vòng đời duyệt |
| `expert_rule_management` | `/expert-rules` | Quy tắc chuyên gia, revision, liên kết tới thuật ngữ và metric, vòng đời duyệt |
| `own_knowledge` | `/own-knowledge` | Câu hỏi làm rõ của agent, tri thức riêng người dùng dạy, màn duyệt của quản trị viên |
| `conversation` | `/conversations` | Hội thoại và lượt hỏi của người dùng, phản hồi, cấu hình hiển thị kết quả |
| `text2sql` | `/text2sql` | Trả lời câu hỏi bằng SQL: chat, SSE, biểu đồ, truy hồi, đồng bộ chỉ mục Qdrant |
| `superset` | — | Dataset, database, người dùng, nhóm quyền của Superset: không có bảng, không có route |

API nằm dưới `/extensions/text-to-bi/superset-text-to-bi/<prefix>`. Mỗi module có lớp `RestApi` riêng trong
`routes/` (decorator `@api(..., resource_name=...)` của `superset_core`), và `entrypoint.py` import chúng.

Mọi truy vấn vào đối tượng Superset đi qua module `superset`: `services/srv_dataset.py` (`get_dataset`,
`require_dataset`, `datasets_on_database`, `get_database`, `can_access_dataset`, `readable_datasets`) dùng DAO của
`superset_core` nên dataset người gọi không thấy cũng là không tồn tại; `services/srv_user.py` cho người dùng;
`services/srv_role.py` cho nhóm quyền và permission FAB qua security manager. Bảng extension tham chiếu bảng Superset
bằng FK (`tables.id`, `dbs.id`, `ab_user.id`); model chuẩn của Superset được import, không định nghĩa lại
(`data_dictionary/models/superset_catalog.py`).

### Cấu trúc một module

```text
modules/<module>/
├── models/          # bảng của module trong schema text_to_bi; __init__.py liệt kê các model
├── repositories/    # truy vấn, kế thừa BaseRepository / ChildRepository; flush, không commit
├── schemas/         # Pydantic: thân request và response
├── services/        # quy tắc nghiệp vụ, kiểm tra quyền theo dataset; không đọc request
├── routes/          # lớp RestApi: đọc request, kiểm tra quyền, gọi service, commit
├── dependencies.py  # tạo service / repository với db.session
├── exceptions.py    # lỗi của module, kế thừa common/base_exceptions.py
└── migrations.py    # ensure_<module>_tables(): tạo bảng của module
```

- Gọi giữa các module đi qua service, repository, model, exception hoặc migration của module kia, không qua route.
- Model đã có chủ sở hữu thì import từ module đó; không tạo model, bảng hay migration trùng.

### Migration

Không có migration Alembic. Route đầu tiên đụng tới bảng gọi `ensure_<module>_tables()` trong `migrations.py` của
module; hàm `create_all(checkfirst=True)` các bảng của module (thêm cột mới bằng `ALTER TABLE … IF NOT EXISTS` khi
cần), một lần cho mỗi process, giữ PostgreSQL advisory lock để các worker không chạy song song. Các hàm gọi nối tiếp
theo phụ thuộc FK:

```text
ensure_text2sql_tables → ensure_own_knowledge_tables → ensure_expert_rule_tables → ensure_glossary_tables
  → ensure_metric_tables → ensure_business_model_tables → ensure_data_dictionary_tables
ensure_text2sql_tables → ensure_conversation_tables
```

`auth/migrations.py` (`ensure_auth_roles`) không tạo bảng mà tạo nhóm quyền và permission FAB. `migrations.py` ở gốc
backend còn hàm `ensure_tables()` nhưng không route nào gọi.

## Frontend

- React 17, TypeScript, webpack 5. `webpack.config.js` dùng `ModuleFederationPlugin` (tên
  `textToBi_supersetTextToBi`, expose `./index` = `src/index.tsx`, chia sẻ `react` / `react-dom` singleton của
  Superset); bundle phục vụ từ `/api/v1/extensions/text-to-bi/superset-text-to-bi/`.
- `src/index.tsx` gọi `/auth/me` một lần, rồi thêm menu vào navbar Superset (`ul[data-test="navbar-top"]`) và gắn
  `<App>` dưới `header#main-menu` khi đường dẫn là `/text-to-bi/`. Backend phục vụ trang đó bằng `TextToBIView`
  (`render_app_template` của Superset).
- Ba menu, mỗi menu mở một mục của cùng trang qua `/text-to-bi/?section=<segment>` (`features/workspace/
  workspace-layout.tsx`):

  | Menu | Mục (`section`) |
  | --- | --- |
  | AI Agent | Hỏi dữ liệu (`chat`), Tri thức riêng (`own-knowledge`) |
  | Mô hình dữ liệu | Từ điển (`dictionary`), Mô hình (`model`), Dòng dữ liệu (`lineage`) |
  | Quản trị dữ liệu | Tổng quan (không có `section`), Metric (`metrics`), Thuật ngữ (`glossary`), Quy tắc (`rules`) |

  Menu chỉ hiện các mục người dùng mở được (`canOpenSection`, xem [hanh-vi.md](hanh-vi.md#quyền-từng-mục-giao-diện));
  không mở được mục nào thì extension không thêm gì vào navbar.
- `src/app.tsx` chọn workspace theo mục; `src/features/<module>/` giữ `api.ts` (hook SWR), `types.ts` và component của
  từng mục; `src/lib/` giữ `api.ts` (`apiFetch`, cookie phiên và CSRF), `navigation.tsx` (điều hướng trong trang bằng
  query string), `access.ts`, `theme.ts`, `sse.ts`.
- `src/components/` là shadcn style `base-nova` dựng trên Base UI; `src/lib/react-compat.ts` thay
  `useSyncExternalStore` / `useId` mà React 17 không có.
- Tailwind v4 chạy trong trang Superset nên `styles/globals.css` bỏ preflight: chỉ sinh token và utility, quy tắc nền
  tảng gói trong `.tb-page` (gốc `AppShell`). Popup portal vào gốc đó để giữ token; chế độ sáng/tối lấy từ màu nền
  Superset và đặt `data-theme-mode` trên host.

## Text2SQL

- **Nguồn dữ liệu:** câu hỏi chạy trên một database Superset có engine PostgreSQL. SQL do agent viết qua
  `sql_guard.validate_select` (một câu `SELECT`) rồi chạy bằng SQL Lab của Superset (`superset_query.py`) với quyền
  của người hỏi; số dòng giới hạn bởi `TEXT2SQL_QUERY_MAX_ROWS`.
- **Chỉ mục:** metadata (bảng, cột, metric, thuật ngữ, quy tắc, tri thức riêng) được embedding qua OpenRouter
  (`TEXT2SQL_EMBEDDING_MODEL`) và lưu trong Qdrant, collection `TEXT2SQL_COLLECTION` (mặc định
  `text2sql_semantics_v1`). `services/ingestion_triggers.py` nghe `after_flush` của SQLAlchemy, ghi job vào
  `text2sql_ingestion_jobs` và sau commit gửi task Celery `text_to_bi.text2sql.process_ingestion_job` cho
  `superset-worker`. Quản trị viên dựng lại toàn bộ chỉ mục bằng `POST /text2sql/ingestion/sync {database_id}`; chưa có
  giao diện cho việc này.
- **Mô hình:** `agent_package/get_chat_models.py` tạo `ChatOpenAI` trỏ `OPENROUTER_BASE_URL` với
  `OPENROUTER_MODEL`. Giá trị PII được che bằng Presidio (`pii_masker.py`) trước khi gửi mô hình và mở lại trong câu
  trả lời.
- **Chat graph:** `chat_service.py` chạy graph LangGraph (`chat_graph.py`) gồm tiền xử lý, trả lời từng câu hỏi con
  bằng tool agent, tổng hợp. Câu hỏi cần làm rõ dừng graph (`interrupt`); snapshot lưu ở
  `text2sql_chat_checkpoints` để lượt sau tiếp tục bằng `resume_id`.
- **SSE:** `POST /text2sql/chat/stream` trả `text/event-stream`. Route mở một thread chạy `asyncio`, thread đó mở thêm
  thread chạy `ChatStream._work`; sự kiện (`turn`, `tool`, `question_started`, `answer_delta`, `clarification`,
  `done`, `error`…) đi qua hàng đợi, và `: keep-alive` mỗi 10 giây. Mọi thread bọc bằng `with_request_user`
  (`services/chat_stream.py`): `copy_current_request_context` cộng gán lại `g.user`, vì security manager đọc người dùng
  từ `g` khi agent liệt kê dataset được phép truy vấn.
- **Session trên thread của LangGraph:** LangGraph chạy các node trên thread pool của nó; `db.session` gắn theo thread
  và chỉ được gỡ khi app context của thread kết thúc, điều thread pool không bao giờ làm. Session bỏ ngỏ giữ
  transaction và lock của mọi bảng đã đọc, khiến `ALTER TABLE` của migration chờ mãi và mọi lệnh đọc xếp hàng sau
  nó. Vì vậy mọi hàm chạy trên thread pool (`preprocess`, `answer_question`, `synthesize` trong `chat_service.py`, các
  tool trong `agent_tools.py`) bọc bằng `release_thread_session` (`common/utils/thread_session.py`): hàm gỡ session nó
  tự mở, giữ nguyên session của nơi gọi. Code mới chạy trên thread ngoài request phải làm như vậy.

## Superset 6.1 và Python 3.10

- Backend chạy trong image Superset 6.1, Python 3.10, SQLAlchemy 1.4 (`requires-python = ">=3.10,<3.11"`, Ruff
  `target-version = "py310"`). Không dùng cú pháp mới hơn Python 3.10.
- Import nặng của Superset chỉ cần khi chạy thì import trong hàm, để test cục bộ (Python 3.12, `superset` giả lập)
  vẫn import được module.
- Sau khi sửa backend, chạy `uv run scripts/compat.py` khi stack đang chạy để biên dịch và import mọi module trong
  container Superset.
