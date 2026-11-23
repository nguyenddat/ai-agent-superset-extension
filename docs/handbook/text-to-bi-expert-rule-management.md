# Expert Rule Management

`expert_rule_management` lưu quy tắc nghiệp vụ của chuyên gia theo dataset Superset: điều kiện có cấu trúc, ngoại lệ, câu hỏi ví dụ và liên kết tới thuật ngữ, metric đã duyệt. Module không nhận và không chạy SQL tự do; Text2SQL đọc quy tắc đang áp dụng làm tri thức cho agent.

## Dữ liệu sở hữu

- `ExpertRule` (`text_to_bi.expert_rules`): `dataset_id`, `name`, `normalized_name`; tên duy nhất không phân biệt hoa thường trong một dataset.
- `ExpertRuleRevision` (`expert_rule_revisions`): `number`, `description`, `conditions`, `exceptions`, `examples` (JSON), `status` (`draft`, `approved`, `revoked`).
- `ExpertRuleGlossaryLink` (`expert_rule_glossary_links`): ghim `term_id` cùng đúng `glossary_revision_id` đang phục vụ lúc lưu.
- `ExpertRuleMetricLink` (`expert_rule_metric_links`): `kind` (`metric`, `superset_metric`), `target_key`, `fingerprint` SHA-256 của dataset, tên, biểu thức, mô tả và cờ hoạt động của metric. Không có khóa ngoại cứng tới metric vì `target_key` nhận cả UUID metric tự tạo lẫn ID metric Superset.
- `expert_rule_domains`: bảng nối với `business_domains` của module [Business Model](text-to-bi-business-model.md).
- `dataset_id` là khóa ngoại tới `SupersetDataset.id`, `ON DELETE CASCADE`. Thuật ngữ đọc qua `GlossaryService`, metric qua `MetricService`; không khai báo lại model của hai module đó.

## Vòng đời và điều kiện áp dụng

- Tạo quy tắc tạo revision 1 `draft`. Sửa nội dung hoặc liên kết tạo revision `draft` mới (kể cả khi revision hiện tại đã `revoked`); chỉ đổi miền nghiệp vụ thì không. Duyệt, thu hồi và chống ghi đè theo `expected_revision` giống Glossary.
- Mỗi điều kiện tham chiếu cột bằng `column_name` có trên dataset. Toán tử và kiểu giá trị phải khớp nhau (ví dụ `in`/`not_in` cần mảng, so sánh lớn/nhỏ cần số, `is_null`/`is_not_null` cần `null`).
- Quy tắc cần ít nhất một thuật ngữ cùng dataset có bản đang phục vụ và còn liên kết sống tới dataset. Metric liên kết phải phân giải được qua `MetricService.resolve` (metric tự tạo phải `approved` và đang hoạt động).
- Một revision "còn sống" khi mọi cột điều kiện còn tồn tại, mỗi thuật ngữ ghim vẫn đang phục vụ đúng revision đã ghim, và mỗi metric vẫn có cùng fingerprint. Duyệt từ chối bản nháp không còn sống. Bản đã duyệt mà không còn sống thì rời discovery (`is_discoverable=false`) cho đến khi được sửa và duyệt lại.
- Duyệt, thu hồi và xóa quy tắc đang có bản phục vụ cần quyền review (Steward hoặc Admin).
- Thay đổi trên bốn bảng quy tắc tạo job lập chỉ mục Text2SQL cho topic `expert_rule` và `own_knowledge`.

## Lớp module

- `models/expert_rule.py`: bốn model và bảng nối miền nghiệp vụ.
- `repositories/`: repository cho quy tắc, revision, liên kết thuật ngữ, liên kết metric.
- `services/expert_rule_service.py`: kiểm tra nội dung, vòng đời revision, ghim liên kết, kiểm tra còn sống, discovery và options; không đọc request, không commit.
- `dependencies.py`: tạo service trên `superset.extensions.db.session`.
- `routes/route_expert_rule.py`: `TextToBIExpertRuleAPI`, kiểm tra body, CSRF, commit.
- `migrations.py`: `ensure_expert_rule_tables()` gọi `ensure_glossary_tables()` (chuỗi này gọi tiếp Metric và Business Model), rồi tạo bảng quy tắc và bảng nối miền nghiệp vụ dưới advisory lock `74_116_301`.

## API và quyền

Resource `/extensions/text-to-bi/superset-text-to-bi/expert-rules`; chi tiết ở [Expert Rule Management API](text-to-bi-expert-rule-management-api.md).

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/datasets/<dataset_id>` | Danh sách quy tắc kèm `is_discoverable` |
| GET | `/datasets/<dataset_id>/discovery` | Quy tắc đã duyệt và còn sống |
| GET | `/datasets/<dataset_id>/options` | Cột, thuật ngữ đang phục vụ và metric đang hoạt động để soạn quy tắc |
| GET | `/<rule_id>` | Chi tiết quy tắc |
| GET | `/<rule_id>/revisions` | Lịch sử revision |
| POST | `/` | Tạo quy tắc nháp |
| PUT | `/<rule_id>` | Tạo revision nháp mới hoặc đổi miền nghiệp vụ |
| POST | `/<rule_id>/approve` | Duyệt revision nháp hiện tại |
| POST | `/<rule_id>/revoke` | Thu hồi bản đang phục vụ |
| DELETE | `/<rule_id>` | Xóa quy tắc |

## Giao diện

Mục **Quy tắc** trong menu **Quản trị dữ liệu** (`/text-to-bi/?section=rules&dataset=<id>&rule=<uuid>`), mở với người có quyền xem. Trang chọn một dataset, hiện bốn ô thống kê (Tổng quy tắc, AI đang áp dụng, Chờ duyệt, Cần cập nhật), tìm kiếm, lọc trạng thái và danh sách. Trạng thái hiển thị: Đang áp dụng, Cần cập nhật (bản đã duyệt không còn sống), Chờ duyệt thay đổi, Chờ duyệt, Đã thu hồi. Chi tiết hiện mô tả, điều kiện, ngoại lệ, câu hỏi ví dụ, thuật ngữ, metric và so sánh bản nháp với bản đang phục vụ; người duyệt có thể giữ một phần thay đổi (lưu thành bản nháp mới rồi duyệt, nên cần cả quyền sửa). Form soạn lấy cột từ `/options` và thuật ngữ từ `glossary/datasets/<id>/discovery`. Thẻ **Quy tắc AI đang áp dụng** ở mục Tổng quan đếm theo dataset.

## Gọi từ module khác

Module khác gọi public `ExpertRuleService` (`discovery`, `options`, `create_rule`), không truy vấn bảng quy tắc trực tiếp. Own Knowledge tạo quy tắc khi promote qua `create_rule`; Text2SQL lập chỉ mục kết quả `discovery` và agent đọc quy tắc qua công cụ `get_expert_rule`.
