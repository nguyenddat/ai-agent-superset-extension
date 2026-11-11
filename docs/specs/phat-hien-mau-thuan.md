# Đặc tả: Tự động phát hiện thuật ngữ và rule mâu thuẫn

Trạng thái: **đã triển khai, chờ duyệt** · Ngày: 11/11/2026 · Phạm vi: Semantic Layer (module `consistency`, màn hình
"Mâu thuẫn")

## 1. Bối cảnh

Business Glossary và Expert Rules do nhiều người soạn, qua nhiều lần sửa. AI Agent dùng cả hai để hiểu câu hỏi, nên khi
một thuật ngữ nói "trên 50 mm" còn rule tương ứng lọc "≥ 50", hoặc hai thuật ngữ cùng nhận một từ đồng nghĩa, câu trả lời
phụ thuộc vào việc AI Agent tình cờ đọc nội dung nào trước. Quản trị viên khó tự thấy các chỗ này vì chúng nằm ở hai
màn hình khác nhau.

Đặc tả này phân loại các kiểu mâu thuẫn, chọn kiểu nào kiểm bằng quy tắc (deterministic) và kiểu nào cần mô hình AI, và
mô tả màn hình để quản trị viên xem và bỏ qua mâu thuẫn.

Ngoài phạm vi: gợi ý gom nhóm thuật ngữ hoặc rule giống nhau (làm bằng embedding, ở một nhánh khác). Đặc tả này chỉ đọc
nhóm đã có (`group_id`) để không báo trùng tên giữa các thuật ngữ cùng nhóm.

## 2. Dữ liệu thực tế (metadata database, 11/11/2026)

- 10 thuật ngữ đã duyệt (id 3 đến 12); thuật ngữ 8 nằm trong nhóm 1 ("test").
- 2 rule đang dùng, đều đã duyệt:
  - Rule 1 "Ngày nắng nóng gay gắt": `nhiet_do_cao_nhat_c ≥ 37`, gắn thuật ngữ 3 "Nắng nóng" và metric 17.
  - Rule 2 "Ngày mưa lớn": `tong_mua_mm ≥ 50` và `< 100`, gắn thuật ngữ 6 "Mưa lớn" và metric 20.
- Thuật ngữ 6 "Mưa lớn" định nghĩa: "Ngày có tổng lượng mưa trên 50 mm; trên 100 mm là mưa rất to."

Kết quả chạy bộ kiểm tra trên dữ liệu này:

| Kiểm tra | Kết quả |
| --- | --- |
| Quy tắc: trùng tên, từ đồng nghĩa | Không có |
| Quy tắc: ngưỡng rule so với định nghĩa thuật ngữ | **1 mâu thuẫn:** rule 2 lọc "≥ 50", thuật ngữ 6 nói "trên 50" ("> 50"). Ngày mưa đúng 50 mm được rule tính là mưa lớn, định nghĩa thì không |
| Quy tắc: câu hỏi mẫu so với điều kiện rule | Không có ở bản hiện tại. Bản sửa thứ 2 của rule 1 từng có điều kiện "≥ 37" nhưng câu hỏi mẫu viết "từ 35°C trở lên"; kiểm tra này sẽ bắt được trường hợp đó |
| Quy tắc: điều kiện rỗng, hai rule chồng lấn | Không có |
| Ứng viên gửi AI | 16 cặp |

Một lần chạy thử với mô hình AI (6 cặp đầu, 9,5 giây):

- Không mâu thuẫn: "Lượng mưa" với "Mưa lớn", "Độ ẩm" với "Nồm ẩm", "Rét đậm" với metric nhiệt độ trung bình, "Ngày có
  mưa" với "Số ngày có mưa".
- Mâu thuẫn: thuật ngữ "Rét đậm" với metric nhiệt độ thấp nhất. AI giải thích: "Định nghĩa rét đậm dựa trên nhiệt độ
  trung bình, còn metric tính nhiệt độ thấp nhất."
- Mâu thuẫn: rule "Ngày mưa lớn" với thuật ngữ "Mưa lớn" (ranh giới 50 mm). Cặp này đã được kiểm tra bằng quy tắc bắt
  được, nên bản chính thức không gửi lại cho AI.

Kết luận: cả hai nhánh đều có ích. Quy tắc bắt chính xác lệch ngưỡng; AI bắt được lệch nghĩa giữa định nghĩa và công
thức metric mà quy tắc không đọc được.

## 3. Các kiểu mâu thuẫn

Chỉ kiểm nội dung quản trị viên còn dùng: bản sửa hiện tại của mỗi thuật ngữ và rule, ở trạng thái `draft` (chờ duyệt)
hoặc `approved`. Bản đã từ chối, đã thu hồi và bản cũ không được kiểm. Metric được kiểm khi một thuật ngữ gắn nó.

### 3.1 Kiểm bằng quy tắc

| `kind` | Giữa | Phát hiện khi | Vì sao dùng quy tắc |
| --- | --- | --- | --- |
| `term_name_clash` | thuật ngữ, thuật ngữ | Tên hoặc từ đồng nghĩa của hai thuật ngữ trùng nhau sau khi chuẩn hóa (như kiểm tra trùng tên của Glossary). Bỏ qua hai thuật ngữ cùng nhóm | So khớp chuỗi, không cần hiểu nghĩa |
| `rule_conditions_empty` | một rule | Các điều kiện của rule không thể cùng đúng, ví dụ `> 50` và `< 30`, `= 'A'` và `in ('B', 'C')`, `is_null` và `> 0` | Phép giao khoảng và tập giá trị |
| `rule_rule_same_term` | rule, rule | Hai rule cùng gắn một thuật ngữ, cùng dataset, nhưng điều kiện khác nhau | Cùng một khái niệm phải lọc cùng một tập dòng |
| `rule_rule_overlap` | rule, rule | Hai rule gắn thuật ngữ khác nhau, cùng dataset, cùng tập cột điều kiện, vùng điều kiện giao nhau nhưng không lồng hẳn vào nhau | Một ngày vừa là "A" vừa là "B" thường là lỗi ranh giới. Rule lồng nhau (như "mưa rất to" nằm trong "mưa lớn") là bình thường nên không báo |
| `rule_term_threshold` | rule, thuật ngữ | Ngưỡng định nghĩa thuật ngữ nói bằng lời khác ngưỡng của rule gắn thuật ngữ đó, kể cả chỉ khác `>` với `≥` | Đọc được ngưỡng từ câu văn bằng mẫu cụm từ tiếng Việt cố định |
| `rule_example_threshold` | một rule | Câu hỏi mẫu (`intent`) của rule nói một ngưỡng khác điều kiện | Như trên |

Cách so điều kiện:

- Mỗi cột của rule là một miền giá trị: khoảng số (biên mở hoặc đóng, có thể không chặn một phía), tập giá trị được
  phép (`equals`, `in`), tập giá trị bị loại (`not_equals`, `not_in`), và `is_null`, `is_not_null`.
- `50` và `50.0` là một giá trị; `true` và `1` là hai giá trị khác nhau.
- `contains` và `not_contains` không được suy luận, coi như cho phép mọi giá trị, nên không bao giờ báo mâu thuẫn từ chúng.
- Hai rule chỉ được so khi cùng dataset.

Cách đọc ngưỡng từ câu văn:

- Chỉ đọc mệnh đề đầu (trước `;`, xuống dòng hoặc dấu chấm kết câu), vì phần sau thường là ngoại lệ, ví dụ "trên 100 mm
  là mưa rất to".
- Các cụm nhận ra: "trên", "dưới", "vượt quá", "từ X trở lên/xuống", "không quá", "không dưới", "ít nhất", "tối đa",
  "từ X đến Y", và các ký hiệu `>`, `≥`, `<`, `≤`. Số sau "ngày", "tháng", "năm", "tuần", "lần" là số đếm nên bị bỏ qua.
- Chỉ so những biên câu văn nói. "Trên 50 mm" chỉ so biên dưới, không coi là mâu thuẫn với biên trên `< 100` của rule.
- Thuật ngữ được so với cột ngưỡng duy nhất của rule; nếu rule có nhiều cột ngưỡng thì chọn cột ngưỡng duy nhất mà thuật
  ngữ gắn. Không xác định được cột thì không so.

### 3.2 Kiểm bằng mô hình AI

| `kind` | Giữa | Vì sao cần AI |
| --- | --- | --- |
| `term_term_meaning` | thuật ngữ, thuật ngữ | Hai định nghĩa văn xuôi nói khác nhau về cùng một thứ |
| `term_metric_meaning` | thuật ngữ, metric nó gắn | Định nghĩa nói một đại lượng, công thức tính đại lượng khác (ví dụ trung bình với thấp nhất) |
| `rule_term_meaning` | rule, thuật ngữ nó gắn | Điều kiện, ngoại lệ hoặc câu hỏi mẫu của rule trái nghĩa với định nghĩa ngoài phần ngưỡng |
| `rule_rule_meaning` | rule, rule | Ngoại lệ hoặc câu hỏi mẫu của hai rule cùng dataset nói trái nhau |

Chỉ các cặp có liên quan mới được gửi (lọc rẻ, không gọi AI):

- Hai thuật ngữ: cùng gắn một cột hoặc metric, cùng nhóm, hoặc định nghĩa của thuật ngữ này nhắc tên hoặc từ đồng nghĩa
  của thuật ngữ kia.
- Thuật ngữ với từng metric nó gắn; rule với từng thuật ngữ nó gắn.
- Hai rule cùng dataset có chung thuật ngữ hoặc chung cột điều kiện.
- Cặp đã bị một kiểm tra quy tắc báo thì không gửi lại.

Mô hình là chat model OpenRouter sẵn có (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL` trong `core/config.py`). Mỗi lần gọi
gửi tối đa 6 cặp, chạy song song; mỗi lượt kiểm tra gửi tối đa 24 cặp chưa có kết quả. Mô hình trả về cho từng cặp
`contradiction` (đúng/sai) và một câu giải thích tiếng Việt ngắn (tối đa 600 ký tự). Câu hỏi gửi kèm cho từng kiểu nêu rõ
chỉ tính mâu thuẫn thật, không tính khác cách diễn đạt hay một bên chi tiết hơn.

Khi không gọi được AI, phần quy tắc vẫn chạy và màn hình hiện một dòng nhắc:

| Tình huống | Dòng nhắc |
| --- | --- |
| Chưa cấu hình khóa | "Chưa cấu hình OPENROUTER_API_KEY nên chưa kiểm tra được mâu thuẫn về nghĩa giữa các định nghĩa." |
| Lỗi khi gọi | "Không gọi được mô hình AI; các cặp chưa kiểm tra sẽ được kiểm tra ở lần sau." |
| Còn cặp vượt giới hạn 24 | "Còn N cặp chưa được AI kiểm tra; bấm “Kiểm tra lại” để tiếp tục." |

## 4. Dấu vân tay, bộ nhớ đệm và bỏ qua

- **Dấu vân tay** của một mâu thuẫn là sha256 của `kind` cùng loại, id và `content_hash` của từng nội dung. Thuật ngữ
  và rule dùng `content_hash` của bản sửa; metric dùng sha256 của tên, tên hiển thị và biểu thức.
- **Kết quả AI** lưu theo dấu vân tay trong `text_to_bi_contradiction_judgement`, gồm cả kết quả "không mâu thuẫn". Cặp
  không đổi nội dung thì không gọi AI lại. Kết quả của cặp không còn là ứng viên bị xóa, nhưng chỉ sau một lượt đã kiểm
  hết, để lỗi hoặc giới hạn số cặp không làm mất kết quả cũ.
- **Mâu thuẫn** lưu trong `text_to_bi_contradiction`, mỗi cặp một dòng theo `pair_key` (kiểu và các nội dung). Mỗi lượt
  kiểm tra đối chiếu với kết quả mới:
  - Mâu thuẫn mới được thêm, trạng thái `open`.
  - Mâu thuẫn không còn bị phát hiện thì bị xóa.
  - Mâu thuẫn đã bỏ qua mà dấu vân tay không đổi thì giữ `dismissed`. Nếu một trong hai nội dung đổi, dòng mở lại
    (`open`) và xóa lý do bỏ qua.
- Bỏ qua cần lý do (bắt buộc, tối đa 512 ký tự); lưu người bỏ qua và thời điểm.

## 5. API

Cả hai route chỉ cho quản trị viên (`require_admin`), có CSRF, đúng thứ tự decorator của handbook và commit một lần.

| Route | Việc làm | Trả về |
| --- | --- | --- |
| `POST /semantic-layer/contradictions/check` | Chạy toàn bộ kiểm tra, cập nhật bảng mâu thuẫn | `contradictions` và `semantic` (`status`: `checked`, `pending`, `unavailable`, `failed`; `unchecked`; `message`) |
| `POST /semantic-layer/contradictions/<id>/dismiss` | Bỏ qua một mâu thuẫn, body `{ "reason": "..." }` | `contradiction` |

Mỗi mâu thuẫn có `id`, `kind`, `found_by` (`rule` hoặc `ai`), `status`, `items` (loại, id, tên), `evidence` (các dòng bằng
chứng, hoặc nội dung đã gửi AI), `explanation`, `detected_at`, `dismiss_reason`, `dismissed_by_name`, `dismissed_at`.

Lỗi:

- 400 khi thiếu lý do hoặc lý do dài quá 512 ký tự.
- 404 khi không còn mâu thuẫn đó: "Không tìm thấy mâu thuẫn; bấm “Kiểm tra lại” để cập nhật danh sách."
- 409 khi hai lượt kiểm tra cùng lưu: "Một lượt kiểm tra khác vừa lưu kết quả; bấm “Kiểm tra lại”."

Không có route chỉ đọc danh sách: màn hình luôn kiểm tra lại khi mở, để danh sách khớp nội dung hiện tại.

## 6. Giao diện

Menu "Quản trị nghiệp vụ" có thêm mục "Mâu thuẫn", chỉ quản trị viên thấy.

- Mở màn hình thì chạy kiểm tra. Cột trái liệt kê mâu thuẫn, chưa xử lý trước, sau đó theo kiểu. Mỗi dòng ghi tên hai
  nội dung, kiểu mâu thuẫn, và "AI" hoặc "Đã bỏ qua". Phía trên có số mâu thuẫn chưa xử lý và nút "Kiểm tra lại".
- Cột phải hiện kiểu, trạng thái, cách phát hiện (quy tắc hay AI), thời điểm phát hiện, và ba phần:
  - "Nội dung liên quan": thuật ngữ và rule là liên kết, bấm vào thì mở Business Glossary hoặc Expert Rules với nội dung
    đó được chọn. Metric chỉ hiện tên.
  - "Bằng chứng", hoặc "Nội dung AI đã đọc".
  - "Vì sao mâu thuẫn", hoặc "Nhận định của AI".
- Nút "Bỏ qua" mở hộp thoại nhập lý do. Mâu thuẫn đã bỏ qua hiện người bỏ qua, thời điểm và lý do.
- Dòng nhắc về AI (mục 3.2) hiện phía trên chi tiết.

## 7. Chưa làm

- Không suy luận `contains` và `not_contains`.
- Không so đơn vị: "50 mm" và "5 cm" không được quy đổi.
- Thuật ngữ gắn nhiều cột ngưỡng thì chỉ so khi xác định được đúng một cột.
- Metric trong danh sách mâu thuẫn chưa mở được màn hình Metrics.
- Không có kiểm tra định kỳ: mâu thuẫn chỉ cập nhật khi quản trị viên mở màn hình hoặc bấm "Kiểm tra lại".

## 8. Kiểm thử

- `tests/test_contradiction_detection.py`:
  - Phép giao khoảng ở biên (`>=` với `>`), danh sách `in`, khoảng mở, `is_null`.
  - Đọc ngưỡng từ câu văn.
  - Từng kiểu kiểm bằng quy tắc, dấu vân tay đổi theo nội dung, chọn ứng viên cho AI.
- `tests/test_contradiction_review.py`:
  - Đọc kết quả AI với mô hình giả: chia lô, bộ nhớ đệm, không có khóa, gọi lỗi, giới hạn số cặp.
  - Giữ và mở lại mâu thuẫn đã bỏ qua.
  - Service với repository giả.
  - Thứ tự decorator, route commit một lần, 400, 403, 404, 409.
