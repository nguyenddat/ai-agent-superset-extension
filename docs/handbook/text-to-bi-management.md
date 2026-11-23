# Nhóm Quản trị dữ liệu trong `superset-text-to-bi`

Menu **Quản trị dữ liệu** trên navbar Superset gom các mục quản trị tri thức nghiệp vụ mà agent Text2SQL được dùng. Mọi mục là một section của trang `/text-to-bi/`, chọn bằng `?section=`:

| Mục | URL | Module backend | Tài liệu |
| --- | --- | --- | --- |
| Tổng quan | `/text-to-bi/` (section rỗng) | đọc từ nhiều module | mục [Tổng quan](#tổng-quan) dưới đây |
| Metric | `?section=metrics` | `metric_management` | [Metric Management](text-to-bi-metric-management.md), [API](text-to-bi-metric-management-api.md) |
| Thuật ngữ | `?section=glossary` | `glossary_management` | [Glossary Management](text-to-bi-glossary-management.md), [API](text-to-bi-glossary-management-api.md) |
| Quy tắc | `?section=rules` | `expert_rule_management` | [Expert Rule Management](text-to-bi-expert-rule-management.md), [API](text-to-bi-expert-rule-management-api.md) |

Cả bốn mục cần quyền xem Text to BI (`can_view`, `canOpenSection` trong `features/workspace/workspace-layout.tsx`). Mục Tri thức riêng ([Own Knowledge](text-to-bi-own-knowledge.md)) thuộc menu **AI Agent**, chỉ Admin mở được; nó tạo bản ghi trong ba module trên khi promote.

## Quy tắc chung của ba module

- Bảng nằm trong schema PostgreSQL `text_to_bi`, ID là UUID v7. Mỗi metric, thuật ngữ, quy tắc gắn với một dataset Superset qua `tables.id` (`ON DELETE CASCADE`); tên duy nhất trong dataset, không phân biệt hoa thường.
- Trạng thái nội dung: `draft`, `approved`, `revoked`. Metric giữ trạng thái trên chính dòng metric; thuật ngữ và quy tắc giữ mỗi lần sửa thành một revision, bản nháp mới không thay bản đã duyệt đang phục vụ, và ghi phải gửi `expected_revision`.
- AI chỉ dùng nội dung đã duyệt: metric tự tạo `approved` và đang hoạt động, thuật ngữ có bản phục vụ, quy tắc có bản phục vụ còn sống (cột, thuật ngữ, metric ghim vẫn khớp).
- Phụ thuộc một chiều: Quy tắc → Thuật ngữ → Metric. Module trên gọi public service của module dưới (`GlossaryService`, `MetricService.resolve`), không truy vấn bảng của nhau.
- Mỗi module có bảng nối miền nghiệp vụ (`metric_domains`, `glossary_term_domains`, `expert_rule_domains`) tới `business_domains` của [Business Model](text-to-bi-business-model.md); form tạo/sửa có bộ chọn miền nghiệp vụ.
- Route ghi sở hữu transaction: gọi `ensure_*_tables()`, gọi service, rồi `db.session.commit()`; `handle_errors` rollback và trả `{code, message}`, `rollback_on_error` trả `500` cho lỗi không lường trước. Route ghi dùng CSRF của Superset (header `X-CSRFToken`).
- Migration nối chuỗi: `ensure_expert_rule_tables()` → `ensure_glossary_tables()` → `ensure_metric_tables()` → `ensure_business_model_tables()`; cả ba dùng advisory lock `74_116_301` và `checkfirst`.
- Mỗi lần ghi bảng của ba module (và bảng `sql_metrics` của Superset) tạo job lập chỉ mục Text2SQL cho database chứa dataset, để chỉ mục Qdrant theo kịp; xem [Text2SQL](text-to-bi-text2sql.md).

Dữ liệu của các extension cũ trước khi hợp nhất không được chuyển sang các bảng này.

## Quyền

| Thao tác | Điều kiện |
| --- | --- |
| Đọc danh sách, chi tiết, discovery | `can_read` của `text_to_bi_api` + quyền xem (Viewer, Editor, Steward, Admin) + đọc được dataset trong Superset |
| Tạo, sửa, xóa bản nháp | `can_write` + quyền sửa (Editor, Steward, Admin) + đọc được dataset |
| Duyệt, thu hồi, xóa nội dung đang phục vụ | thêm quyền review (Steward, Admin) |

Quyền dataset của Superset áp dụng cho mọi role, kể cả Admin. Role và permission được mô tả ở [Auth](text-to-bi-auth.md).

## Tổng quan

Section Tổng quan (`features/workspace/workspace-overview.tsx`) hiện các thẻ theo thứ tự: Tỷ lệ bảng và cột đã mô tả, hai thẻ top bảng của từ điển dữ liệu, Bảng đã phân miền nghiệp vụ, Bảng đã có dòng dữ liệu, Bảng đã có metric, Thuật ngữ AI đang dùng, Quy tắc AI đang áp dụng, và với Admin thêm Tri thức riêng của người dùng. Thẻ miền nghiệp vụ, dòng dữ liệu và tri thức riêng theo database đang chọn (`?database=`, mặc định database đầu tiên). Backend chưa có API đếm chung, nên thẻ metric, thuật ngữ, quy tắc gọi API danh sách cho từng dataset người dùng đọc được (lấy từ `data-dictionary/summary`).

## Giao diện ba mục quản trị

Bundle frontend là React 17, shadcn (base-nova trên Base UI) và Tailwind v4 trong phạm vi `.tb-page`, nạp vào Superset bằng webpack Module Federation. Ba mục Metric, Thuật ngữ, Quy tắc có cùng bố cục: chọn một dataset (`?dataset=`, mặc định dataset đầu tiên đọc được), bốn ô thống kê, ô tìm kiếm, bộ lọc, danh sách và khung chi tiết hoặc form tạo/sửa bên cạnh. Nút tạo/sửa chỉ hiện khi `can_edit`, nút duyệt/thu hồi chỉ hiện khi `can_review` (đọc từ `GET /auth/me`); metric Superset chỉ đọc. Header có nút mở danh sách dataset của Superset. Frontend gọi API bằng cookie phiên Superset và lấy CSRF token từ `/api/v1/security/csrf_token/` cho yêu cầu ghi.
