# Handbook

Tài liệu module: [Data Lineage trong Text to BI](text-to-bi-data-lineage.md),
[Metric Management trong Text to BI](text-to-bi-metric-management.md),
[Glossary Management trong Text to BI](text-to-bi-glossary-management.md),
[Expert Rule Management trong Text to BI](text-to-bi-expert-rule-management.md),
[Own Knowledge trong Text to BI](text-to-bi-own-knowledge.md),
[Conversation trong Text to BI](text-to-bi-conversation.md).

Handbook ghi những gì cả nhóm đã thống nhất khi viết code trong repository này: quy ước code, kiến trúc backend và hành
vi chung của API. Người và agent viết code đều đọc nó trước khi sửa code; khi một quy ước đổi, sửa handbook trong cùng
commit với code.

| Tài liệu | Nội dung |
| --- | --- |
| [quy-uoc-code.md](quy-uoc-code.md) | Độ dài dòng, đặt tên, import, docstring và comment, dữ liệu, test, tài liệu, commit message |
| [kien-truc.md](kien-truc.md) | Các lớp `common`, `core`, `modules`; module chia theo nghiệp vụ; cấu trúc một module |
| [hanh-vi.md](hanh-vi.md) | Exception và mã lỗi, thứ tự decorator của route, transaction, quyền và CSRF |
| [text-to-bi-data-lineage.md](text-to-bi-data-lineage.md) | Model, API, quyền và migration của module data lineage trong Text to BI |
| [text-to-bi-auth.md](text-to-bi-auth.md) | User model, quyền truy cập và role của module auth trong Text to BI |
| [text-to-bi-management.md](text-to-bi-management.md) | Backend ba module quản lý của extension hợp nhất đang triển khai |

Đặc tả từng tính năng nằm ở [docs/specs/](../specs/); handbook chỉ ghi quy tắc dùng chung cho mọi tính năng.

## Phạm vi

- Quy ước code áp dụng cho toàn repository: Python và TypeScript của cả hai extension, script, DAG Airflow.
- Kiến trúc và hành vi áp dụng cho cả hai backend: Semantic Layer (`extensions/semantic-layer/backend`) và AI Agent
  (`extensions/ai-agents/backend`). Hai extension đóng gói riêng nên mỗi bên có `common` và `core` của mình; chỗ hai
  bên khác tên (lớp lỗi gốc, hàm migration) được ghi rõ ở từng mục.
