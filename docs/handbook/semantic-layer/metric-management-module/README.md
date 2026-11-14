# Module `metric_management`

Mô tả luồng xử lý các API của module quản lý metric trong backend Semantic Layer:
`extensions/semantic-layer/backend/src/text_to_bi/superset_semantic_layer/modules/metric_management/`. Module giữ định
nghĩa nghiệp vụ của một metric Superset, giá trị mặc định khi đọc nó, bản duyệt (contract) cùng lịch sử duyệt, và việc
chạy metric đã duyệt qua ChartData của Superset.

Quy tắc chung về lỗi, decorator, transaction và quyền nằm ở [hanh-vi.md](../../hanh-vi.md); cấu trúc module nằm ở
[kien-truc.md](../../kien-truc.md). Đặc tả nghiệp vụ của giá trị mặc định nằm ở
[docs/specs/metric-grain-moc-thoi-gian-bo-loc.md](../../../specs/metric-grain-moc-thoi-gian-bo-loc.md).

| Tài liệu | Route file trong `routes/` | API |
| --- | --- | --- |
| [route-crud-metric-def.md](route-crud-metric-def.md) | `route_crud_metric_def.py` | Định nghĩa, giá trị mặc định |
| [route-metric-contract.md](route-metric-contract.md) | `route_metric_contract.py` | Danh sách, duyệt, lịch sử, chạy |

## Đường dẫn

Hai route mixin `MetricDefinitionRoutes` và `MetricContractRoutes` được ghép vào `SemanticLayerAPI`
(`registry.py`, `resource_name="semantic-layer"`). Superset đặt API của extension dưới
tiền tố mà frontend (`SEMANTIC_LAYER_API` trong `frontend/src/features/semantic-layer/constants.ts`) và AI Agent
(`modules/semantic_layer/services/client.py`) cùng dùng:

```text
{API} = /extensions/text-to-bi/superset-semantic-layer/semantic-layer
```

Các đường dẫn trong tài liệu viết tương đối với `{API}`.

## Các lớp

```text
routes/      MetricDefinitionRoutes, MetricContractRoutes      ← đọc request, kiểm tra quyền, commit, trả response
utils/       util_serializer.py                                ← đổi model và dataclass thành JSON trả về
services/    MetricDefService, MetricContractService,          ← quy tắc nghiệp vụ, không đọc request, không commit
             MetricEventService, MetricExecuteService,
             srv_metric_formula, srv_metric_query_defaults
repositories/ MetricDefinitionRepository,                      ← mọi truy vấn vào ba bảng của module
             MetricContractRepository, MetricContractEventRepository
models/      MetricDefinition, MetricContract, MetricContractEvent
```

- **Model** (`models/model_metric.py`): ba bảng trong metadata database của Superset (xem mục [Bảng](#bảng)).
- **Repository** (`repositories/repo_metric_definition.py`, `repo_metric_contract.py`, `repo_metric_contract_event.py`):
  kế thừa `BaseRepository`; `create` và `update` flush ngay, `delete` không flush. Repository của event được
  `MetricEventService` gọi với `flush=False`.
- **Dependency** (`dependencies.py`): `metric_definition_repository()`, `metric_contract_repository()`,
  `metric_contract_event_repository()`, mỗi hàm gắn repository với `db.session` của request.
- **Service**:
  - `services/srv_metric_def.py`: `MetricDefService` đọc, ghi, xóa định nghĩa và lưu giá trị mặc định.
  - `services/srv_metric_contract.py`: `MetricContractService` (danh sách metric, đề xuất, duyệt, thu hồi) và các hàm
    `metric_contract_hash`, `metric_contract_state`, `metric_contract_ineligibility`, `contract_is_approved_current`,
    `review_reason`.
  - `services/srv_metric_event.py`: `MetricEventService` ghi và đọc lịch sử duyệt.
  - `services/srv_metric_execute.py`: `MetricExecuteService`, `planned_metric_chart`, `run_chart_query`.
  - `services/srv_metric_formula.py`: `parse_contract_metric` đọc công thức bằng sqlglot; `formula_row_kinds`.
  - `services/srv_metric_query_defaults.py`: `MetricQueryDefaults`, `checked_query_defaults`,
    `applied_query_defaults`, và ngữ cảnh thời gian đọc từ Data Dictionary (`dataset_time_contexts`).
- **Serializer** (`utils/util_serializer.py`): `serialize_metric_definition`, `serialize_metric_contract`,
  `serialize_metric_events`, `serialize_metric_entry`, `serialize_query_dataset`, `serialize_users`.
- **Lỗi** (`exceptions.py`): lỗi của module, kế thừa `common/exceptions`.
- **Enum** (`schemas/status_enum.py`): `ContractOrigin` (`manual`, `ai_agent`). Trạng thái duyệt dùng `ReviewStatus`
  chung (`common/schemas/status_enum.py`: `draft`, `approved`, `revoked`).

Ngoài các route dưới đây, API `POST /metric-candidates` trong module này gọi `MetricContractService.propose_for_agent` và `count_agent_drafts`,
còn `expert_rule_management`, `glossary_management` đọc contract qua service và repository của module này. AI Agent
đọc `/metrics/query-metadata` qua HTTP; module Metrics tự xác định trạng thái hiện hành và chỉ công bố các dataset người gọi được đọc.

## Bảng

| Model | Bảng | Một dòng là |
| --- | --- | --- |
| `MetricDefinition` | `text_to_bi_metric_definition` | Định nghĩa và giá trị mặc định của một metric |
| `MetricContract` | `text_to_bi_metric_contract` | Bản duyệt của một định nghĩa |
| `MetricContractEvent` | `text_to_bi_metric_contract_event` | Một bước trong lịch sử duyệt |

- `text_to_bi_metric_definition`: unique trên `metric_id`; `business_definition`, `unit`, `steward_id` và sáu cột mặc
  định (`grain`, `row_kind_value`, `time_column`, `time_window`, `time_anchor`, `default_filters` dạng JSON text); FK
  `sql_metrics.id` và `tables.id` với `ON DELETE CASCADE`.
- `text_to_bi_metric_contract`: unique trên `definition_id` (CASCADE); `metric_name`, `expression`, `expression_hash`,
  `status`, `origin`, `owner_id`, `approver_id`/`approved_at`, `revoker_id`/`revoked_at`, cùng cột audit của
  `AuditMixinNullable`.
- `text_to_bi_metric_contract_event`: chỉ thêm; `action` ∈ `candidate`, `approve`, `revoke`, `definition`; giữ
  `metric_name`, `expression`, `expression_hash`, `definition_snapshot` lúc đó; `metric_id`, `dataset_id` là ID trần,
  `definition_id` là FK `ON DELETE SET NULL`, nên lịch sử còn sau khi định nghĩa bị xóa.

Bảng của Superset mà module đọc (qua module `superset` hoặc qua quan hệ của `SqlaTable`): `tables`, `sql_metrics`,
`table_columns`, `dbs`, `ab_user`. Bảng của Data Dictionary mà module đọc để kiểm tra và áp giá trị mặc định:
`text_to_bi_dataset_dictionary`, `text_to_bi_column_dictionary`, `text_to_bi_dataset_grain`.

## Khung chung của một route

Mọi route của module đi qua cùng một chuỗi decorator, từ ngoài vào trong:

1. `@expose` khai báo method và đường dẫn.
2. `@protect()` và `@permission_name("read" | "write")` của Flask-AppBuilder: chưa đăng nhập hoặc thiếu permission
   `can_read` / `can_write` trên `text_to_bi_semantic_layer_api` thì FAB trả lỗi trước khi vào hàm. Nhóm quyền
   "Semantic Layer Viewer" và "Semantic Layer Query" chỉ được cấp `can_read` (`access_control/services/roles.py`);
   route ghi còn gọi `require_admin()` trong thân hàm.
3. `@safe`: lỗi không ai bắt được (ví dụ `RuntimeError` của `ensure_dictionary_tables`) thành 500.
4. Route thay đổi dữ liệu: `@csrf_protected` (403 "CSRF token không hợp lệ." khi header `X-CSRFToken` sai) rồi
   `@rollback_on_error` (rollback, 500 "Could not save the change.").
5. `@handle_errors` (`core/database.py`): bắt `SemanticLayerError`, rollback, trả `status` và `message` của lỗi.
6. `@requires_metric` hoặc `@requires_database` (`modules/superset/dependencies.py`), nằm sát hàm, dưới
   `handle_errors`, nên lỗi 404 của chúng cũng thành response JSON:
   - `requires_metric`: lấy `dataset_id`, `metric_id` khỏi URL, gọi `require_dataset(dataset_id)` (404 "Dataset not
     found."), tìm metric trong `dataset.metrics` (404 "Không tìm thấy metric này trong dataset."), truyền `dataset` và
     `metric` vào hàm.
   - `requires_database`: đọc `database_id` từ query string (`type=int`), thiếu hoặc không phải số là 400
     "database_id is required.", không có database là 404 "Database not found.".
7. Trong thân hàm: kiểm tra vai trò (`require_admin`, `require_semantic_layer_view` hoặc `require_semantic_layer_query`
   của `core/security.py`), `ensure_dictionary_tables()`, gọi service, `db.session.commit()` nếu ghi, serialize.

Vì decorator `requires_*` chạy trước kiểm tra vai trò trong thân hàm, người không có quyền vẫn nhận 404 khi dataset hoặc
metric không tồn tại, và 403 khi chúng tồn tại.

## Trạng thái hiển thị của metric

`metric_contract_state(contract, dataset, metric, defaults)` trả trạng thái mà danh sách và bản duyệt cùng dùng:

| `state` | Khi nào |
| --- | --- |
| `not_started` | Chưa có contract, metric đủ điều kiện đề xuất |
| `ineligible` | Chưa có contract, `metric_contract_ineligibility` trả lý do |
| `draft` | Contract `draft`, metric đủ điều kiện và `expression_hash` khớp mã băm hiện tại |
| `approved` | Contract `approved` và `contract_is_approved_current` đúng |
| `outdated` | Contract `draft` hoặc `approved` nhưng metric, dataset hoặc giá trị mặc định đã đổi |
| `revoked` | Contract `revoked` |

`metric_contract_hash` băm SHA-256 của: dataset ID, metric ID, tên và công thức metric, catalog, schema, bảng, SQL của
dataset ảo, kiểu datasource, định danh kết nối (`connection_identity`: id, tên, uuid, backend của database), biểu thức
của cột đo và, khi có, `query_defaults`. Đổi một trong số đó là bản duyệt mất hiệu lực.

`metric_contract_ineligibility` từ chối metric có tên không phải định danh `[A-Za-z_][A-Za-z0-9_]*`, công thức không
đọc được bởi `parse_contract_metric` (một AVG/COUNT/MAX/MIN/SUM trên cột, có thể bọc `CASE WHEN`, hoặc tỷ lệ
`hệ số * AGG(...) / NULLIF(AGG(...), 0)`), hoặc dùng cột không có, không active, hay là cột tính toán.
