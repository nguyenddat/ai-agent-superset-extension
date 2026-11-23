# Handbook

Handbook ghi những gì cả nhóm đã thống nhất khi viết code trong repository này: kiến trúc, hành vi chung của API và
quy ước code. Người và agent viết code đều đọc nó trước khi sửa code; khi một quy ước đổi, sửa handbook trong cùng
commit với code.

Repository chỉ còn một extension Superset 6.1: `superset-text-to-bi` (`extensions/text-to-bi`), bản chuyển ứng dụng
standalone (Next.js/FastAPI) vào Superset.

## Quy tắc dùng chung

| Tài liệu | Nội dung |
| --- | --- |
| [kien-truc.md](kien-truc.md) | Superset làm host, các lớp backend, module, migration, trang frontend và menu, Text2SQL (Qdrant, OpenRouter, LangGraph, SSE) |
| [hanh-vi.md](hanh-vi.md) | Exception và mã lỗi, thứ tự decorator, transaction, nhóm quyền, quyền từng mục giao diện, kiểm tra quyền dataset, CSRF |
| [quy-uoc-code.md](quy-uoc-code.md) | Độ dài dòng, đặt tên, import, comment, dữ liệu, cấu hình, test, frontend, tài liệu, commit message |
| [text-to-bi-management.md](text-to-bi-management.md) | Menu Quản trị dữ liệu (Tổng quan, Metric, Thuật ngữ, Quy tắc): quy tắc chung của ba module quản trị và các mục giao diện |

## Tài liệu module

| Module | Mô tả | API |
| --- | --- | --- |
| `auth` | [text-to-bi-auth.md](text-to-bi-auth.md) | [text-to-bi-auth-api.md](text-to-bi-auth-api.md) |
| `data_dictionary` | [text-to-bi-data-dictionary.md](text-to-bi-data-dictionary.md) | [text-to-bi-data-dictionary-api.md](text-to-bi-data-dictionary-api.md) |
| `business_model` | [text-to-bi-business-model.md](text-to-bi-business-model.md) | [text-to-bi-business-model-api.md](text-to-bi-business-model-api.md) |
| `data_lineage` | [text-to-bi-data-lineage.md](text-to-bi-data-lineage.md) | [text-to-bi-data-lineage-api.md](text-to-bi-data-lineage-api.md) |
| `metric_management` | [text-to-bi-metric-management.md](text-to-bi-metric-management.md) | [text-to-bi-metric-management-api.md](text-to-bi-metric-management-api.md) |
| `glossary_management` | [text-to-bi-glossary-management.md](text-to-bi-glossary-management.md) | [text-to-bi-glossary-management-api.md](text-to-bi-glossary-management-api.md) |
| `expert_rule_management` | [text-to-bi-expert-rule-management.md](text-to-bi-expert-rule-management.md) | [text-to-bi-expert-rule-management-api.md](text-to-bi-expert-rule-management-api.md) |
| `own_knowledge` | [text-to-bi-own-knowledge.md](text-to-bi-own-knowledge.md) | [text-to-bi-own-knowledge-api.md](text-to-bi-own-knowledge-api.md) |
| `conversation` | [text-to-bi-conversation.md](text-to-bi-conversation.md) | [text-to-bi-conversation-api.md](text-to-bi-conversation-api.md) |
| `text2sql` | [text-to-bi-text2sql.md](text-to-bi-text2sql.md) | [text-to-bi-text2sql-api.md](text-to-bi-text2sql-api.md) |
| `superset` | — | [text-to-bi-superset-api.md](text-to-bi-superset-api.md) |

Kế hoạch gộp hai extension cũ vào text-to-bi nằm ở
[docs/specs/gop-extension-theo-standalone.md](../specs/gop-extension-theo-standalone.md); quy trình phát hành ở
[docs/release.md](../release.md).

## Phạm vi

- Quy ước code áp dụng cho toàn repository: Python và TypeScript của extension, script trong `scripts/`, môi trường
  giả lập trong `simulation/` (Superset, warehouse, DAG Airflow).
- Kiến trúc và hành vi áp dụng cho backend `extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/` và
  frontend `extensions/text-to-bi/frontend/src/`.
