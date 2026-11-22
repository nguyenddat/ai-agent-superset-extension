# Expert Rule Management

`expert_rule_management` lưu quy tắc nghiệp vụ theo dataset Superset bằng điều kiện có cấu trúc, ngoại lệ, ví dụ và các liên kết tới glossary/metric đã được kiểm tra. Module không nhận hoặc thực thi SQL tự do.

## Chủ sở hữu model và bảng

- `ExpertRule`, `ExpertRuleRevision`, `ExpertRuleGlossaryLink` và `ExpertRuleMetricLink` là model do module này sở hữu trong schema `text_to_bi`.
- `ExpertRule.dataset_id` tham chiếu `SupersetDataset.id`, model chuẩn import từ `modules.data_dictionary.models`.
- Liên kết thuật ngữ tham chiếu trực tiếp `GlossaryTerm` và `GlossaryRevision` do `glossary_management` sở hữu; không tạo model glossary trùng.
- Metric không có FK cứng vì `target_key` nhận UUID metric thủ công hoặc ID metric Superset; `MetricService.resolve` xác thực liên kết và fingerprint nội dung.
- `expert_rule_domains` là bảng nối do module này khai báo. `business_domains` thuộc module business model; migration chỉ tạo bảng nối khi model owner được đăng ký.

Mỗi lần tạo/sửa nội dung tạo revision mới. Revision lưu description, điều kiện, ngoại lệ, ví dụ, IDs của đúng revision glossary và fingerprint metric. Trạng thái revision: `draft`, `approved`, `revoked`. `expected_revision` ngăn ghi đè từ màn hình cũ. Rule chỉ xuất hiện trong discovery khi revision được duyệt còn hợp lệ: các cột còn tồn tại, glossary revision vẫn đang được phục vụ và metric vẫn có cùng fingerprint.

## Lớp module

- `models/expert_rule.py`: bốn model và bảng nối domain.
- `repositories/`: repository riêng cho rule, revision, glossary link và metric link.
- `services/expert_rule_service.py`: validation, revision lifecycle, snapshot links, kiểm tra trạng thái live và discovery; service không đọc request hoặc commit.
- `dependencies.py`: tạo service trên `superset.extensions.db.session`.
- `routes/route_expert_rule.py`: kiểm tra payload/quyền, CSRF và transaction.
- `migrations.py`: gọi migration Glossary/Metric trước để FK/resolver sẵn sàng, sau đó tạo bảng Expert Rule; dùng advisory lock và `checkfirst`.

## API và quyền

Base resource là `/extensions/text-to-bi/superset-text-to-bi/expert-rules`:

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/datasets/<dataset_id>` | Danh sách rule và trạng thái discovery; cần quyền xem và đọc dataset |
| GET | `/datasets/<dataset_id>/discovery` | Các rule đã duyệt còn hợp lệ |
| GET | `/datasets/<dataset_id>/options` | Cột, thuật ngữ đang discoverable và metric để chọn |
| GET | `/<rule_id>` | Chi tiết rule/revision |
| GET | `/<rule_id>/revisions` | Lịch sử revision |
| POST | `/` | Tạo rule nháp; cần quyền sửa dataset |
| PUT | `/<rule_id>` | Tạo revision nháp hoặc cập nhật domain; cần `expected_revision` |
| POST | `/<rule_id>/approve` | Duyệt revision; cần Text to BI Steward hoặc Admin |
| POST | `/<rule_id>/revoke` | Thu hồi rule đang được phục vụ; cần Steward hoặc Admin |
| DELETE | `/<rule_id>` | Xóa rule; xóa rule đang phục vụ cần Steward hoặc Admin |

Điều kiện tham chiếu `column_name` trên dataset; operator và `value_type` được giới hạn bởi Pydantic schema. Một rule cần ít nhất một glossary term đã duyệt có link live tới dataset. Metric liên kết phải thuộc cùng dataset, đang hoạt động và được `MetricService` phân giải. Ghi API cần CSRF; quyền Superset trên dataset vẫn được áp dụng cùng quyền Text to BI.

## Gọi từ module khác và migration

`entrypoint.py` đăng ký `TextToBIExpertRuleAPI`. Module khác gọi public `ExpertRuleService.options()` hoặc `discovery()`; không query các bảng Expert Rule trực tiếp. Với glossary, module dùng public `GlossaryService`; với metric dùng `MetricService.resolve()`.

`ensure_expert_rule_tables()` gọi `ensure_glossary_tables()` trước; migration Glossary gọi tiếp migration Metric. Migration này không tạo bảng Superset, Glossary, Metric hoặc `business_domains`. Khi Business Model được tích hợp, entrypoint phải import model owner `BusinessDomain` trước lần migration đầu tiên để tạo bảng nối domain.
