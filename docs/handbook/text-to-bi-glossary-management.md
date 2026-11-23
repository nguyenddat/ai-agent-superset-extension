# Glossary Management

`glossary_management` lưu thuật ngữ nghiệp vụ theo dataset Superset, lịch sử revision của từng thuật ngữ và liên kết của thuật ngữ tới bảng, cột, metric. Bản nháp mới không thay bản đã duyệt mà AI đang dùng; mọi thao tác ghi trên thuật ngữ đã có dùng `expected_revision` để chống ghi đè từ màn hình cũ.

## Dữ liệu sở hữu

- `GlossaryTerm` (`text_to_bi.glossary_terms`): `dataset_id`, `canonical_name`, `normalized_name`. Tên được gộp khoảng trắng và duy nhất không phân biệt hoa thường trong một dataset (`uq_glossary_term_name`).
- `GlossaryRevision` (`glossary_revisions`): `term_id`, `number` (duy nhất theo thuật ngữ), `definition`, `synonyms`, `status` (`draft`, `approved`, `revoked`).
- `GlossaryLink` (`glossary_links`): liên kết của từng revision, `kind` là `table`, `column`, `metric` hoặc `superset_metric`, `target_key` là ID dataset, tên cột, UUID metric tự tạo hoặc ID metric Superset. Cột được giữ bằng tên vì Superset có thể tạo lại dòng `table_columns` khi đồng bộ dataset.
- `glossary_term_domains`: bảng nối thuật ngữ với `business_domains` của module [Business Model](text-to-bi-business-model.md).
- `dataset_id` là khóa ngoại tới `SupersetDataset.id`, `ON DELETE CASCADE`. Metric được phân giải qua `MetricService.resolve`; Glossary không khai báo lại model metric.

## Vòng đời

- Tạo thuật ngữ tạo revision 1 ở trạng thái `draft`.
- Sửa định nghĩa, từ đồng nghĩa hoặc liên kết tạo revision `draft` mới khi nội dung khác revision hiện tại, hoặc khi revision hiện tại đã `revoked`. Chỉ đổi miền nghiệp vụ thì không tạo revision.
- Duyệt chỉ áp dụng cho revision mới nhất khi nó đang `draft`. Thu hồi tạo revision `revoked` mới chép nội dung bản đang phục vụ.
- Bản đang phục vụ (serving) là revision `approved` mới nhất, miễn là không có revision `revoked` mới hơn nó. Discovery và AI chỉ dùng bản này.
- Mọi liên kết được kiểm tra khi lưu: `table` phải là chính dataset, `column` phải là cột hiện có, `metric`/`superset_metric` phải phân giải được qua `MetricService.resolve` (metric tự tạo phải `approved` và đang hoạt động). Discovery bỏ các liên kết không còn sống.
- Duyệt, thu hồi và xóa thuật ngữ đang có bản phục vụ cần quyền review (Steward hoặc Admin); tạo, sửa, xóa bản nháp cần quyền sửa và quyền đọc dataset.
- Thay đổi trên ba bảng glossary tạo job lập chỉ mục Text2SQL cho topic `glossary`, `expert_rule`, `own_knowledge`.

## Lớp module

- `models/glossary.py`: ba model và bảng nối `glossary_term_domains`.
- `repositories/`: một repository cho thuật ngữ, revision và liên kết.
- `services/glossary_service.py`: vòng đời revision, kiểm tra liên kết, `expected_revision`, quyền, discovery; không đọc request, không commit.
- `dependencies.py`: tạo service trên `superset.extensions.db.session`.
- `routes/route_glossary.py`: `TextToBIGlossaryAPI`, kiểm tra body, CSRF, commit.
- `migrations.py`: `ensure_glossary_tables()` gọi `ensure_metric_tables()` trước, rồi tạo ba bảng glossary và bảng nối miền nghiệp vụ dưới advisory lock `74_116_301`.

## API và quyền

Resource `/extensions/text-to-bi/superset-text-to-bi/glossary`; chi tiết ở [Glossary Management API](text-to-bi-glossary-management-api.md).

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/datasets/<dataset_id>` | Danh sách thuật ngữ của dataset |
| GET | `/datasets/<dataset_id>/discovery` | Thuật ngữ có bản đang phục vụ, kèm liên kết còn sống |
| GET | `/<term_id>` | Thuật ngữ với revision hiện tại và bản đang phục vụ |
| GET | `/<term_id>/revisions` | Lịch sử revision |
| POST | `/` | Tạo thuật ngữ với revision nháp đầu tiên |
| PUT | `/<term_id>` | Tạo revision nháp mới hoặc đổi miền nghiệp vụ |
| POST | `/<term_id>/approve` | Duyệt revision nháp hiện tại |
| POST | `/<term_id>/revoke` | Thu hồi bản đang phục vụ |
| DELETE | `/<term_id>` | Xóa thuật ngữ |

## Giao diện

Mục **Thuật ngữ** trong menu **Quản trị dữ liệu** (`/text-to-bi/?section=glossary&dataset=<id>&term=<uuid>`), mở với người có quyền xem. Trang chọn một dataset, hiện bốn ô thống kê (Tổng thuật ngữ, AI đang dùng, Chờ duyệt, Đã liên kết dữ liệu), tìm kiếm, lọc theo trạng thái và danh sách. Trạng thái hiển thị gộp từ revision: Đã duyệt, Chờ duyệt thay đổi (có bản nháp mới trong khi bản cũ vẫn phục vụ), Chờ duyệt, Đã thu hồi. Khi duyệt một bản thay đổi, người duyệt có thể giữ lại một phần thay đổi: frontend lưu phần được giữ thành bản nháp mới (`PUT`) rồi duyệt bản đó, nên cần cả quyền sửa lẫn quyền review. Thẻ **Thuật ngữ AI đang dùng** ở mục Tổng quan đếm theo dataset.

## Gọi từ module khác

Module khác dùng public `GlossaryService` (`discovery`, `serving_revision`, `live_links`, `get_term`, `create_term`), không truy vấn bảng glossary trực tiếp. Expert Rule ghim đúng revision đang phục vụ của thuật ngữ; Own Knowledge tạo thuật ngữ khi promote qua `create_term`; Text2SQL lập chỉ mục kết quả `discovery`.
