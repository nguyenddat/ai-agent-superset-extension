# Đặc tả: gộp hai extension thành một, theo backend của standalone

**Trạng thái:** đã làm xong. Lập ngày 2026-11-20; cập nhật 2026-11-23: đủ 7 giai đoạn, hai extension cũ
(`extensions/ai-agents`, `extensions/semantic-layer`) đã bị xóa khỏi repository. Chỗ triển khai khác với kế hoạch được
ghi ở mục [Khác với kế hoạch](#khác-với-kế-hoạch).

## Mục tiêu

Thay hai extension cũ (Semantic Layer và AI Agent) bằng một extension `superset-text-to-bi`. Backend
của extension mới có cấu trúc và nghiệp vụ như backend của repository `ai-agent-superset-standalone`. Chỗ khác chỉ do
chạy trong Superset: bảng nguồn là dataset của Superset, người dùng và quyền là của Superset.

## Quyết định đã chốt

| Vấn đề | Quyết định |
| --- | --- |
| Bảng và cột nguồn | Dataset (`tables`) và cột (`table_columns`) của Superset. Bỏ module `database_connection` của standalone. |
| Người dùng và quyền | Module `auth` mới dùng phiên đăng nhập, nhóm quyền và quyền dataset của Superset. |
| Dữ liệu cũ | Bắt đầu sạch: không chuyển dữ liệu từ bảng `text_to_bi_*` của hai extension cũ. |
| Tạo và nâng cấp bảng | Kiểu `ensure_tables()` hiện tại: chạy một lần mỗi process, dưới PostgreSQL advisory lock. |
| Chỉ mục vector | Qdrant chạy trong compose; job ingestion chạy trên Celery worker của Superset (`superset-worker`). |

## Ràng buộc của Superset 6.1

- Python 3.10, SQLAlchemy 1.4.54, Pydantic 2.11, Flask 2.3, Flask-AppBuilder. Code chuyển từ standalone phải bỏ cú pháp
  mới hơn 3.10 (`type X = ...`, generic PEP 695, `datetime.UTC`, `uuid.uuid7`) và kiểu khai báo chỉ có ở SQLAlchemy 2
  (`mapped_column`, `Uuid`).
- Route là `BaseApi` của Flask-AppBuilder (`@expose`, `@protect`, `@permission_name`), không phải FastAPI. Schema
  Pydantic của standalone dùng lại để kiểm tra body và dựng response.
- Session là `superset.db.session`. Route sở hữu transaction như cả hai repository đang làm.

## Cấu trúc

```text
extensions/text-to-bi/
├── extension.json                      # superset-text-to-bi
├── backend/src/text_to_bi/superset_text_to_bi/
│   ├── entrypoint.py                   # đăng ký API và trang
│   ├── migrations.py                   # ensure_tables() của mọi module
│   ├── common/                         # base model, repository, exception, formatter, charts (theo standalone)
│   ├── core/                           # Settings, bảo mật chung (CSRF), xử lý lỗi route
│   ├── agent_package/                  # chat model, embedding, prompt, tool agent (theo standalone)
│   └── modules/<module>/               # models, repositories, schemas, services, routes, utils, dependencies.py
├── backend/tests/
└── frontend/                           # React 17 + shadcn (Base UI), trang /text-to-bi/ chia section
```

Bảng của extension nằm trong schema PostgreSQL `text_to_bi` của metadata database Superset, giữ tên bảng của standalone
(`text_to_bi.table_dictionaries`, …). Không đụng bảng của Superset hay bảng `text_to_bi_*` của hai extension cũ. ID là UUID v7 như standalone
(sinh bằng hàm trong `common`, vì Python 3.10 chưa có `uuid.uuid7`); tham chiếu sang Superset dùng ID số của Superset.

## Ánh xạ module

| Standalone | Extension | Khác biệt |
| --- | --- | --- |
| `database_connection` | `superset` | Đọc `Database`, `SqlaTable`, `TableColumn`; chạy truy vấn chỉ đọc bằng engine của `Database` sau `raise_for_access`. Không lưu URI, không đồng bộ metadata. |
| — | `auth` | Người dùng hiện tại, nhóm quyền Text to BI, kiểm tra quyền dataset, API gán nhóm quyền (`/auth/role-assignments`). Thay mọi `user_id` client gửi và khóa dịch vụ của `own_knowledge`. |
| `data_dictionary` | `data_dictionary` | `table_id` → dataset Superset; cột theo `(dataset_id, column_name)` vì Superset có thể xóa và tạo lại dòng `table_columns` khi ghi đè dataset. Không lưu kiểu dữ liệu, nullable; đọc từ `TableColumn`. |
| `business_model`, `data_lineage` | cùng tên | Tham chiếu dataset thay cho bảng của connection. |
| `metric_management` | cùng tên | Metric của Superset (`SqlMetric`) đọc trực tiếp thay cho đồng bộ qua API. |
| `glossary_management`, `expert_rule_management` | cùng tên | Tham chiếu dataset, cột, metric như trên. |
| `own_knowledge` | cùng tên | `user_id` là `ab_user.id` của người đăng nhập. |
| `conversation` | cùng tên | Như trên. |
| `text2sql` | cùng tên | Truy vấn nguồn qua module `superset` theo quyền người hỏi; Qdrant gọi qua HTTP (`httpx`), job ingestion là Celery task. |

## Phân quyền

Mọi quyền là permission trên view menu `Text to BI` (`modules/auth/services/srv_access.py`, `srv_roles.py`), khai báo
admin-only để Superset không tự gán cho Alpha, Gamma, Public, sql_lab. Quyền dataset của Superset vẫn áp dụng cho
mọi nhóm, kể cả Admin.

| Nhóm quyền | Permission | Được làm |
| --- | --- | --- |
| Admin | mọi permission | Mọi thao tác; riêng section "Tri thức riêng" chỉ Admin mở được |
| Text to BI Viewer | `can_view` | Xem metadata của dataset mình đọc được |
| Text to BI Editor | `can_view`, `can_edit` | Như Viewer, và tạo, sửa, xóa bản nháp metadata |
| Text to BI Steward | `can_view`, `can_edit`, `can_review` | Như Editor, và duyệt, thu hồi, xóa nội dung đã duyệt |
| Text to BI Query | `can_query` | Hỏi dữ liệu (section "Hỏi dữ liệu") trên dataset mình đọc được |

Kế hoạch ban đầu chỉ có Viewer, Editor, Query và để việc duyệt cho Admin; nhóm Steward được thêm khi làm.

## Hạ tầng

- `docker-compose.yml`: thêm `qdrant`. Không có container worker riêng: `superset` và `superset-worker` (Celery) cùng
  nạp extension; task `text_to_bi.text2sql.process_ingestion_job` (`modules/text2sql/worker.py`) chạy trên
  `superset-worker`.
- `simulation/superset/Dockerfile`: thêm thư viện standalone cần mà image chưa có (LangChain, LangGraph, Presidio,
  spaCy, …). Không cần `qdrant-client` vì Qdrant được gọi qua HTTP.
- `scripts/`: chỉ còn phục vụ text-to-bi (`EXTENSION_DIR = extensions/text-to-bi` trong `_common.py`). Bundle là
  `extensions/superset-text-to-bi-0.1.0.supx`, chép vào `/app/superset_home/extensions/` trong container.

## Các giai đoạn

0. Khung: extension, `common`, `core`, `agent_package`, module `superset` và `auth`, `ensure_tables`, trang trống trên
   navbar, script build và deploy.
1. `data_dictionary` và section "Từ điển".
2. `business_model`, `data_lineage`.
3. `metric_management`.
4. `glossary_management`, `expert_rule_management`, `own_knowledge`.
5. `text2sql` (Qdrant, task ingestion, retrieve, chat), `conversation`, section "Hỏi dữ liệu".
6. Gỡ hai extension cũ.

Cả 7 giai đoạn đã xong. Giai đoạn 6 xóa `extensions/ai-agents/`, `extensions/semantic-layer/`, bundle và kiểm tra
riêng của chúng trong `scripts/`; mã cũ chỉ còn trong lịch sử git.

## Khác với kế hoạch

- Frontend không phải một trang nhiều tab. Trang `/text-to-bi/?section=<segment>` thêm ba menu vào navbar Superset:
  "AI Agent" (Hỏi dữ liệu, Tri thức riêng), "Mô hình dữ liệu" (Từ điển, Mô hình, Dòng dữ liệu), "Quản trị dữ liệu"
  (Tổng quan, Metric, Thuật ngữ, Quy tắc).
- Tính năng chỉ extension cũ có đều không được chuyển sang: relationship contract, phát hiện grain, nhập/xuất file,
  phát hiện mâu thuẫn, gợi ý gom nhóm, agent ladder, schema link, public API v1. Grain theo loại dòng và kiểu thời gian
  của cột được giữ theo cách của standalone (`text_to_bi.table_time_grains`, `column_dictionaries.temporal_kind`). Trang
  "Tổng quan" theo standalone.
- Chỉ mục Qdrant (collection `text2sql_semantics_v1`) được dựng lại bằng `POST /text2sql/ingestion/sync`
  `{database_id}` (Admin); chưa có giao diện.
