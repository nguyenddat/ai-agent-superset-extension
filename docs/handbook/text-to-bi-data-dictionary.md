# Module `data_dictionary` của Text to BI

Module nằm tại `extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/data_dictionary/`. Module đọc catalog database, dataset và cột do Superset quản lý, đồng thời lưu các chú giải nghiệp vụ riêng của Text to BI.

## Catalog Superset

`models/superset_catalog.py` export alias tới model Superset, không định nghĩa lại model và không tạo các bảng này:

| Alias | Model Superset | Bảng Superset | Dữ liệu chính |
| --- | --- | --- | --- |
| `SupersetDatabase` | `Database` | `dbs` | Kết nối database đã đăng ký |
| `SupersetDataset` | `SqlaTable` | `tables` | Dataset, database ID, tên bảng, schema, catalog |
| `SupersetDatasetColumn` | `TableColumn` | `table_columns` | Tên, kiểu và metadata cột của dataset |

`repositories/repo_superset_catalog.py` cung cấp truy vấn đọc cho ba model. `services/srv_superset_catalog.py` gom các truy vấn này thành `SupersetCatalogService`; dependency `superset_catalog_service()` dùng `superset.extensions.db.session` hiện hành.

Metadata mở rộng nằm trong schema `text_to_bi`. `TableDictionary.dataset_id` và `ColumnDictionary.dataset_id` tham chiếu trực tiếp `tables.id`; `referenced_dataset_id` cũng tham chiếu dataset Superset. Metadata cột được định danh bằng `(dataset_id, column_name)`, không bằng `table_columns.id`, vì ID dòng cột thuộc vòng đời đồng bộ catalog. Kiểu dữ liệu và cờ thời gian được đọc từ `table_columns`.

Các bảng metadata do extension sở hữu:

| Model | Bảng | Mục đích |
| --- | --- | --- |
| `TableDictionary` | `text_to_bi.table_dictionaries` | Tên hiển thị, mô tả, grain, loại/layout dataset, PII và liên kết catalog chỉ số |
| `ColumnDictionary` | `text_to_bi.column_dictionaries` | Thuật ngữ nghiệp vụ, semantic role, temporal kind, unit/format, key/reference và PII |
| `TableColumnRole` | `text_to_bi.table_column_roles` | Gán vai trò cho cột theo dataset |
| `TableTimeGrain` | `text_to_bi.table_time_grains` | Grain theo loại dòng |
| `IndicatorAggregation` | `text_to_bi.indicator_aggregations` | Aggregation theo mã chỉ số của catalog |
| `ColumnAggregation` | `text_to_bi.column_aggregations` | Aggregation được phép cho cột measure |
| `ColumnSynonym` | `text_to_bi.column_synonyms` | Tên gọi khác của cột |

## Repository, service và route

`repositories/` chứa repository cho dictionary cấp dataset, dictionary cấp cột, các bảng con và catalog Superset. `services/dictionary_service.py` kiểm tra và tổng hợp metadata nghiệp vụ; `services/autofill_service.py` tạo gợi ý bằng mô hình ngôn ngữ. `dependencies.py` khởi tạo các service bằng session Superset.

`routes/route_data_dictionary.py` đăng ký API resource `data-dictionary`:

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/summary` | Tổng hợp dataset có thể truy cập, theo database và schema |
| GET | `/stats` | Thống kê dictionary và các dataset được tham chiếu |
| GET | `/datasets/<dataset_id>` | Đọc dictionary cùng metadata Superset của dataset/cột |
| PUT | `/datasets/<dataset_id>` | Tạo hoặc cập nhật metadata dataset |
| PUT | `/datasets/<dataset_id>/columns` | Lưu metadata cho các cột |
| POST | `/datasets/<dataset_id>/autofill` | Stream gợi ý qua Server-Sent Events |

Route kiểm tra quyền đọc/sửa dataset theo security manager Superset. Các route ghi yêu cầu CSRF và commit trong cùng metadata session; autofill commit theo từng sự kiện trước khi gửi sự kiện đó.

## Migration

`migrations.py` của module cung cấp `ensure_data_dictionary_tables()`. Hàm chỉ tạo bảy bảng extension trong schema `text_to_bi`, dùng `checkfirst` và PostgreSQL advisory lock để chạy an toàn giữa các worker. Model Superset được nạp vào SQLAlchemy metadata để khai báo FK, nhưng không được đưa vào danh sách tạo bảng. Các route gọi migration trước khi truy cập dữ liệu.
