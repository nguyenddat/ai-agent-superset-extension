# Đặc tả: Gợi ý gom nhóm thuật ngữ và expert rule

Trạng thái: **đã làm** · Ngày: 11/11/2026 · Phạm vi: Semantic Layer (Glossary, Expert Rules)

## 1. Vấn đề

Quản trị viên gom các thuật ngữ cùng nghĩa vào nhóm thuật ngữ và các rule tương đồng vào nhóm rule bằng tay (xem
README của extension, mục "Groups of terms and rules"). Khi glossary lớn dần, khó nhận ra "Mưa lớn", "Ngày có mưa" và
"Lượng mưa" nói về cùng một chuyện, hay một thuật ngữ mới nên vào nhóm nào. Tính năng này tìm các mục gần nghĩa nhau
và gợi ý; quản trị viên xác nhận, sửa hoặc bỏ qua từng gợi ý.

## 2. Biểu diễn một mục thành vector

Mỗi mục được viết thành một đoạn văn bản rồi biến thành vector:

| Mục | Văn bản |
| --- | --- |
| Thuật ngữ | `<tên>. Đồng nghĩa: <a>; <b>. <định nghĩa>` của revision hiện tại |
| Expert rule | `<tên>. Thuật ngữ: <các thuật ngữ liên kết>. Điều kiện: <cột> <phép so sánh> <giá trị>; …. Câu hỏi: <câu hỏi> (<cách hiểu>); …` |

Liên kết dataset, cột, metric của thuật ngữ và ngoại lệ của rule không đưa vào: chúng nói dữ liệu nằm ở đâu hoặc
trường hợp biên, và các thuật ngữ trên cùng một dataset sẽ trông giống nhau chỉ vì thế.

### 2.1 Embedding qua OpenRouter

- OpenRouter có endpoint `POST /api/v1/embeddings` theo chuẩn OpenAI, gọi được từ container Superset bằng
  `OPENROUTER_API_KEY` sẵn có. Danh sách `/api/v1/embeddings/models` có các mô hình đa ngôn ngữ (OpenAI
  text-embedding-3, Qwen3 Embedding, BGE-M3, multilingual-e5, Gemini Embedding).
- Mặc định dùng `openai/text-embedding-3-small` (`OPENROUTER_EMBEDDING_MODEL` trong `core/config.py`): đọc được tiếng
  Việt, 1536 chiều, rẻ (10 thuật ngữ mẫu tốn khoảng 0,00001 USD), và là mô hình phổ biến nên ít bị gỡ khỏi OpenRouter.
  Đặt biến này rỗng để chỉ dùng cách dự phòng.
- Vector đã có trong `text_to_bi_text_embedding` được đọc theo (`model`, SHA-256 của văn bản). Khi cache có vector
  tương ứng thì không gọi lại mô hình; phần thiếu được tính và giữ trong bộ nhớ của lần gọi, không lưu cache mới.
  Vì vậy văn bản chưa có trong cache có thể phải gọi mô hình lại ở lần GET sau. Vector dùng JSON (làm tròn 6 chữ số);
  không cần pgvector ở quy mô vài trăm mục.

### 2.2 Cách dự phòng: TF-IDF trên từ

Khi không có khoá, khi `OPENROUTER_EMBEDDING_MODEL` rỗng, hoặc khi lời gọi lỗi (mạng, hết thời gian 20 giây, phản hồi
sai dạng), mọi mục được so bằng TF-IDF trên âm tiết, viết bằng Python thuần (`common/utils/similarity.py`), không thêm
thư viện:

- Chuẩn hoá Unicode NFC và chữ thường, giữ dấu ("mưa" và "mua" là hai từ khác nhau).
- Đặc trưng là từng âm tiết; trọng số `(1 + ln tf) × (ln((1 + n) / (1 + df)) + 1)`, vector chuẩn hoá độ dài 1.
- Trên glossary mẫu, âm tiết đơn tách nhóm gần nghĩa khỏi các cặp không liên quan tốt hơn khi thêm cặp âm tiết hay
  n-gram ký tự.

Một lần gợi ý chỉ dùng một cách cho mọi mục, vì độ tương đồng của hai cách không so được với nhau.

## 3. Gom nhóm lân cận

Độ tương đồng là cosine giữa hai vector. Gom nhóm là phân cụm phân cấp theo liên kết trung bình (average linkage):

1. Mỗi nhóm quản trị viên đã tạo là một cụm cố định; mỗi mục chưa phân nhóm là một cụm riêng.
2. Lặp: ghép hai cụm có độ tương đồng trung bình giữa mọi cặp thành viên cao nhất, khi giá trị đó đạt ngưỡng. Hai nhóm
   có sẵn không bao giờ ghép với nhau.
3. Kết quả: cụm có nhóm có sẵn và thêm mục chưa phân nhóm thành gợi ý **đưa vào nhóm đó**; cụm từ hai mục chưa phân
   nhóm trở lên thành gợi ý **nhóm mới**.

Liên kết trung bình không nối dây chuyền như thành phần liên thông (A gần B, B gần C nhưng A xa C thì C không vào).
Gợi ý chỉ chuyển mục **chưa phân nhóm**: mục đã ở một nhóm là quyết định của quản trị viên và không bị đề nghị chuyển đi.

### 3.1 Ngưỡng

| Cách | Ngưỡng | Đo trên glossary mẫu |
| --- | --- | --- |
| Embedding `text-embedding-3-small` | 0,70 | Ba thuật ngữ về mưa 0,75–0,79; "Độ ẩm" – "Nồm ẩm" 0,72; cặp không liên quan cao nhất 0,67 ("Nắng nóng" – "Giờ nắng") |
| TF-IDF | 0,25 | "Độ ẩm" – "Nồm ẩm" 0,46; nhóm mưa: các cặp 0,24–0,38, liên kết trung bình 0,28; cặp không liên quan cao nhất 0,22 ("Rét đậm" – "Nồm ẩm") |

Đổi sang mô hình embedding khác có thể cần ngưỡng khác (`THRESHOLDS` trong `glossary_management/services/srv_group_suggestion.py`).

### 3.2 Nội dung một gợi ý

- Nhóm đích: nhóm có sẵn, hoặc nhóm mới với tên đề xuất là tên của thành viên trung tâm nhất (tổng độ tương đồng với
  các thành viên khác lớn nhất). Không gọi LLM đặt tên để giữ màn hình nhanh; quản trị viên đổi tên được.
- Từng mục được chuyển, với độ tương đồng trung bình tới phần còn lại của nhóm và mục gần nhất (bằng chứng).
- Các thành viên sẵn có của nhóm đích.
- `fingerprint`: SHA-256 của nhóm đích (rỗng nếu nhóm mới) và danh sách ID mục được chuyển.

## 4. Quản trị viên duyệt gợi ý

Nút "Gợi ý gom nhóm" ở trang Glossary và Expert Rules, chỉ hiện với quản trị viên, mở hộp thoại liệt kê các gợi ý.
Mỗi gợi ý cho phép:

- **Áp dụng** như đề xuất.
- **Sửa rồi áp dụng**: chọn nhóm có sẵn khác hoặc "Nhóm mới", đổi tên nhóm mới, bỏ chọn mục không muốn chuyển.
- **Bỏ qua**: ghi fingerprint vào `text_to_bi_group_suggestion_dismissal` (theo `kind`: `glossary` hoặc
  `expert_rule`). Gợi ý y hệt không hiện lại; khi nhóm đích hay tập mục đổi (thêm thuật ngữ gần nghĩa, một mục đã
  được xếp nhóm), fingerprint đổi và gợi ý mới hiện ra.

Áp dụng dùng đúng service nhóm sẵn có: tạo nhóm (tên trùng trả 409), rồi chuyển từng mục bằng `move_term` /
`move_rule`. Mỗi lần chuyển là một sự kiện `moved` trong lịch sử của mục; revision, content hash, lifecycle version và
trạng thái duyệt giữ nguyên, nên không cần duyệt lại. Mọi bước nằm trong một transaction, commit một lần.

## 5. API

| Route | Mô tả |
| --- | --- |
| `GET …/glossary/group-suggestions`, `GET …/expert-rules/group-suggestions` | Danh sách gợi ý: `method` (`embedding` hoặc `tfidf`), `model`, `threshold`, `suggestions` |
| `POST …/group-suggestions/apply` | `{"member_ids": [...], "group_id": <id>}` hoặc `{"member_ids": [...], "group_name": "..."}`; trả nhóm và ID các mục đã chuyển |
| `POST …/group-suggestions/dismiss` | `{"fingerprint": "<64 ký tự hex>"}` |

Mọi route gọi `require_admin()`. Route ghi có `csrf_protected` và `rollback_on_error` theo thứ tự decorator của
handbook. Service embedding chỉ đọc vector đã cache; vector thiếu được tính trong bộ nhớ và không ghi database.
GET expert rule không commit. GET glossary vẫn có lệnh commit cũ sau khi gợi ý, nhưng service không thêm vector mới;
route glossary còn gọi migration gate theo luồng sẵn có. Không coi hai route đã hoàn toàn giống nhau về transaction.

## 6. Vị trí code

| Phần | File |
| --- | --- |
| TF-IDF, cosine, phân cụm (thuần, không phụ thuộc Superset) | `common/utils/similarity.py` |
| Bảng cache vector và gợi ý bị bỏ qua | `modules/glossary_management/models/model_grouping.py` |
| Gọi OpenRouter, cache, dự phòng | `modules/glossary_management/services/srv_glossary_embedding.py` |
| Dựng gợi ý, fingerprint, bỏ qua, kiểm tra payload áp dụng | `modules/glossary_management/services/srv_group_suggestion.py` |
| Văn bản và áp dụng cho thuật ngữ | `modules/glossary_management/services/srv_glossary_group.py` |
| Văn bản và áp dụng cho rule | `modules/expert_rule_management/services/srv_expert_rule_group.py` |
| Hộp thoại | `frontend/src/features/semantic-layer/GroupSuggestions.tsx` |

Hai bảng mới thuộc module `glossary`; module `expert_rules` dùng chúng qua service của `glossary`, như nó đã dùng
repository thuật ngữ. Không tạo module mới vì gom nhóm là một phần của nghiệp vụ glossary và expert rule.

## 7. Kiểm thử

`tests/test_group_suggestions.py`: chuẩn hoá từ và TF-IDF; phân cụm trên vector cố định (nhóm mới, đưa vào nhóm có
sẵn, hai nhóm có sẵn không ghép, liên kết trung bình không nối dây chuyền); embedding dự phòng khi không có khoá, khi
lời gọi lỗi hoặc sai dạng, đọc cache theo hash; gợi ý trên SQLite với nhóm có sẵn; nhớ gợi ý bị bỏ
qua và hiện lại khi tập mục đổi; áp dụng gợi ý đã sửa (sự kiện `moved`, giữ trạng thái duyệt, tên trùng 409); thứ tự
decorator, quyền admin, commit một lần của route.

Sau sửa lỗi, cần đối chiếu các test cache cũ với hành vi chỉ đọc cache. `test_expert_rule_regressions.py` kiểm tra thêm
savepoint khi tạo dismissal trùng; bộ test cũ hiện còn bị chặn bởi import đường dẫn module trước đợt refactor.
