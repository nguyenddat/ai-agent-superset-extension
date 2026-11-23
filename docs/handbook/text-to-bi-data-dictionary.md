# Module `data_dictionary` của Text to BI

Module nằm tại `extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_dictionary/`. Module đọc
database, dataset và cột do Superset quản lý, và lưu phần mô tả nghiệp vụ của Text to BI cho từng dataset. Đây là nguồn
ngữ nghĩa chính cho agent Hỏi dữ liệu và cho các module mô hình, dòng dữ liệu, metric. Endpoint xem
[Data Dictionary API](text-to-bi-data-dictionary-api.md).

## Catalog Superset

`models/superset_catalog.py` export alias tới model Superset, không định nghĩa lại và không tạo bảng:

| Alias | Model Superset | Bảng |
| --- | --- | --- |
| `SupersetDatabase` | `Database` | `dbs` |
| `SupersetDataset` | `SqlaTable` | `tables` |
| `SupersetDatasetColumn` | `TableColumn` | `table_columns` |
| `SupersetMetric` | `SqlMetric` | `sql_metrics` |

Các module khác import alias từ đây. `repositories/repo_superset_catalog.py` và `services/srv_superset_catalog.py` đọc
catalog bằng session hiện hành; việc tìm dataset theo quyền người gọi đi qua `modules/superset`
([Superset integration](text-to-bi-superset-api.md)).

## Dữ liệu của module

Bảy bảng trong schema `text_to_bi`:

| Model | Bảng | Nội dung |
| --- | --- | --- |
| `TableDictionary` | `table_dictionaries` | Tên hiển thị, mô tả, mô tả grain, `table_kind`, `layout`, danh mục chỉ số, PII |
| `TableColumnRole` | `table_column_roles` | Vai trò cấu trúc của cột trong bảng (`time`, `created_at`, `row_kind`, vai trò chỉ số) |
| `TableTimeGrain` | `table_time_grains` | Độ chi tiết thời gian, theo từng loại dòng nếu bảng có cột `row_kind` |
| `IndicatorAggregation` | `indicator_aggregations` | Phép tổng hợp theo mã chỉ số của bảng danh mục |
| `ColumnDictionary` | `column_dictionaries` | Tên hiển thị, mô tả, thuật ngữ, `semantic_role`, `temporal_kind`, đơn vị, định dạng, khóa, tham chiếu, PII |
| `ColumnAggregation` | `column_aggregations` | Phép tổng hợp được phép cho cột `measure` |
| `ColumnSynonym` | `column_synonyms` | Tên gọi khác của cột |

`TableDictionary.dataset_id` và `ColumnDictionary.dataset_id` tham chiếu `tables.id` (xóa dataset thì xóa từ điển).
Cột được định danh bằng `(dataset_id, column_name)`, không bằng `table_columns.id`, vì Superset có thể đổi ID cột khi
đồng bộ. Kiểu dữ liệu, cờ thời gian và cột tính toán luôn đọc từ Superset. `ColumnDictionary.referenced_dataset_id` và
`referenced_column_name` khai báo khóa ngoại nghiệp vụ; module `data_lineage` suy ra cạnh quan hệ từ chúng.

`ensure_data_dictionary_tables()` (`migrations.py`) tạo riêng bảy bảng với `checkfirst` dưới advisory lock
`74_116_301`, khóa dùng chung với migration tổng `migrations.py` và migration của `business_model`, `data_lineage`. Route gọi hàm này trước khi đọc hoặc ghi.

## Quy tắc

- Đọc cần `can_view` và quyền truy cập dataset trong Superset. Ghi và tự động điền cần `can_edit` cộng quyền truy cập
  dataset. Dataset người gọi không thấy trả 404 như không tồn tại.
- `layout` là `wide`, `indicator_values` hoặc `indicator_catalog`; mỗi layout có tập vai trò cột cho phép và bắt buộc
  (`indicator_values` cần `indicator_key` và `value`; `indicator_catalog` cần `catalog_key`, `catalog_code`,
  `catalog_name`). Bảng `indicator_values` có thể trỏ tới một danh mục chỉ số: dataset khác, cùng database, đọc được,
  đã lưu với layout `indicator_catalog`. `indicator_aggregations` (tối đa 20 mã) chỉ dùng cho bảng danh mục có cột vai
  trò `catalog_aggregation`.
- `table_kind`: `base` hoặc `aggregate`. `semantic_role` của cột: `key`, `measure`, `dimension`, `label`, `time`,
  `row_kind`, `attribute`; cột chưa lưu có vai trò mặc định suy từ kiểu và tên. `temporal_kind`: `date` hoặc
  `timestamp`. Phép tổng hợp cột chỉ dành cho `measure`.
- Cột tham chiếu phải thuộc dataset cùng database mà người gọi đọc được và cột đó phải tồn tại; không được trỏ vào
  chính nó. Mô tả tối đa 2.000 ký tự; tối đa 20 từ đồng nghĩa mỗi cột, mỗi từ tối đa 100 ký tự, trùng bị loại.
- Lưu cột chỉ thay các cột gửi lên; cột không gửi giữ nguyên.
- Mọi thay đổi trên bảng từ điển (và trên dataset, cột Superset) xếp job đồng bộ chỉ mục Qdrant của Text2SQL cho
  database liên quan (`modules/text2sql/services/ingestion_triggers.py`).

## Tự động điền

`services/autofill_service.py` gọi mô hình ngôn ngữ (cấu hình `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`,
`OPENROUTER_MODEL` trong `core/config.py`) qua `services/dictionary_suggester.py`. Cột được gửi theo lô 8 cột, tối đa
300 cột mỗi dataset. Gợi ý chỉ điền chỗ còn trống: tên hiển thị còn bằng tên cột hoặc trống, mô tả, thuật ngữ, đơn vị
chưa có; dòng mới ưu tiên tên và mô tả Superset đã có. Sau các cột, mô hình gợi ý tên, mô tả, grain của bảng và cột
`created_at` nếu bảng chưa có. Mỗi lô được commit trước khi gửi sự kiện SSE. `services/autofill_lock.py` giữ advisory
lock theo dataset nên hai lượt tự động điền trên cùng dataset không chạy song song.

## Giao diện

Menu **Mô hình dữ liệu**, mục **Từ điển** (`/text-to-bi/?section=dictionary&dataset=<id>`), cần `can_view`; mã ở
`frontend/src/features/data-dictionary/`.

- Bộ chọn bảng liệt kê mọi dataset đọc được theo database và schema (từ `GET /summary`).
- Tab **Thông tin bảng**: tên hiển thị, mô tả, grain, loại bảng, PII, cách tổ chức chỉ số (layout), vai trò cột, độ
  chi tiết thời gian, danh mục chỉ số và phép tổng hợp theo mã.
- Tab **Cột**: lọc cột; mỗi cột có tên hiển thị, vai trò, mô tả, khóa chính, duy nhất, PII, cột tham chiếu, từ đồng
  nghĩa, phép tổng hợp.
- **Lưu thay đổi** (hoặc Ctrl/Cmd+S) ghi thông tin bảng rồi các cột đã sửa. Chuyển bảng hoặc chuyển mục khi còn thay
  đổi chưa lưu sẽ được hỏi lại.
- **Tự động điền** chạy autofill qua SSE, chỉ bấm được khi không còn thay đổi chưa lưu; dừng giữa chừng vẫn giữ các lô
  đã lưu.
- Dataset người dùng không sửa được (`can_edit` false trong response) hiển thị chỉ đọc.
- Mục **Tổng quan** dùng `GET /summary` và `GET /stats` cho thẻ độ phủ từ điển và các bảng xếp hạng.

## Kiểm thử

`backend/tests/test_data_dictionary_api.py` và `test_data_dictionary_autofill.py` hiện lỗi ngay khi pytest nạp test vì
`tests/conftest.py` chưa có bản giả cho `superset.connectors` và `superset.models.core`.
