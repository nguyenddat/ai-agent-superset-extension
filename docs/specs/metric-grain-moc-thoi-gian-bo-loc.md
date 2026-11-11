# Đặc tả: Grain, mốc thời gian và bộ lọc mặc định của metric

Trạng thái: **đã làm** · Ngày: 10/11/2026 · Phạm vi: Semantic Layer (metric contract, màn Metric, thực thi) và AI Agent

## 1. Vấn đề

Một metric đã duyệt chỉ có công thức. Cách đọc nó nằm trong đầu người hỏi hoặc do AI Agent đoán:

- "Tổng lượng mưa" đọc theo ngày hay theo tuần? Dữ liệu dự báo có cả theo giờ lẫn theo ngày
  ([grain-va-ngu-nghia-thoi-gian.md](grain-va-ngu-nghia-thoi-gian.md)).
- Hỏi "lượng mưa bao nhiêu" không nêu khoảng thời gian thì tính trên toàn bộ dữ liệu, kể cả dự báo tương lai.
- Một số metric luôn chỉ có nghĩa trên một phạm vi (một vùng, một loại dòng) mà công thức không nói.

Đặc tả này cho mỗi metric ba khai báo, được duyệt cùng công thức và được áp dụng khi chạy.

## 2. Khái niệm

- **Grain**: đơn vị thời gian metric được đọc (`hour`, `day`, `week`, `month`, `quarter`, `year`). Không mịn hơn grain
  của loại dòng metric dùng (grain gốc). `instant` không là grain đọc.
- **Loại dòng**: giá trị của cột phân loại dòng (`loai_quan_sat`) mà metric dùng, trên bảng trộn nhiều grain.
- **Mốc thời gian**: cột thời gian metric đo trên đó, khoảng thời gian mặc định và điểm tính khoảng đó (`now`: thời
  điểm hiện tại theo giờ Việt Nam; `latest_data`: mốc dữ liệu mới nhất của metric).
- **Bộ lọc mặc định**: các bộ lọc `{column, operator, value}` luôn áp dụng trừ khi người gọi lọc chính cột đó.

## 3. Lưu trữ

Thêm vào `text_to_bi_metric_definition` (cùng định nghĩa nghiệp vụ), các cột cho phép rỗng, thêm bằng `ALTER TABLE` trong
`migrations.py`:

| Cột | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `grain` | `VARCHAR(16)` | Grain đọc metric |
| `row_kind_value` | `VARCHAR(255)` | Loại dòng metric dùng |
| `time_column` | `VARCHAR(255)` | Cột thời gian |
| `time_window` | `VARCHAR(32)` | Khoảng mặc định: `last_<n>_<đơn vị>`, `current_<đơn vị>`, `previous_<đơn vị>`, `<đơn vị>_to_date` |
| `time_anchor` | `VARCHAR(16)` | `now` hoặc `latest_data` |
| `default_filters` | `TEXT` | Mảng JSON `{column, operator, value}` |

Khi đọc, Semantic Layer gắn thêm `row_kind_column` và `native_grain` lấy từ từ điển dữ liệu của dataset.

## 4. Kiểm tra khi lưu

`PUT .../dataset/<id>/metrics/<id>/query-defaults` (quản trị viên, CSRF) nhận sáu trường trên. Metric phải có định
nghĩa nghiệp vụ trước. Quy tắc (lỗi 400, thông điệp tiếng Việt):

- Loại dòng phải là loại dòng đã khai báo grain trong từ điển dữ liệu; dataset không có cột phân loại thì không chọn.
- Công thức chỉ tính một loại dòng (`CASE WHEN loai_quan_sat = 'DU_BAO_NGAY'`) thì loại dòng phải là loại đó; để trống
  thì tự điền.
- Dataset có nhiều loại dòng với grain khác nhau: đặt grain hay khoảng thời gian thì phải chọn loại dòng.
- Grain không mịn hơn grain gốc; đơn vị của khoảng thời gian cũng vậy (trừ dòng `instant`).
- Cột thời gian phải là cột ngày hoặc ngày giờ (`is_dttm` hoặc `temporal_kind`), active, không tính toán, lọc được.
  Để trống thì lấy `time_column` của dataset khi có grain hoặc khoảng thời gian.
- Có khoảng thời gian mà không có mốc tính thì mốc là `now`; không có khoảng thì mốc bị bỏ.
- Bộ lọc mặc định: tối đa 10, kiểm tra như bộ lọc khi chạy (cột active, lọc được, phép so sánh hợp lệ, giá trị vô
  hướng hoặc danh sách); không đặt trên cột thời gian hay cột phân loại dòng; mỗi cột một bộ lọc.

Mỗi lần lưu ghi một sự kiện `definition` vào lịch sử duyệt.

## 5. Vòng đời duyệt

Ba khai báo là một phần nghĩa của metric, như công thức. `metric_contract_hash` thêm khối `query_defaults` (kể cả
`row_kind_column` và `native_grain`) khi metric có khai báo; metric chưa có giữ nguyên hash cũ nên không contract nào
hết hiệu lực khi triển khai. Đổi khai báo, hoặc đổi grain của loại dòng trong từ điển dữ liệu, làm contract đã duyệt
thành `outdated`: metric rời catalog, thuật ngữ và expert rule liên kết tới metric đó thành `outdated`, cho tới khi
quản trị viên đề xuất và duyệt lại. Mọi nơi kiểm tra contract (metric, catalog, glossary, expert rule, AI Agent ladder)
đọc khai báo hiện tại qua `metric_query_defaults_for` / `metric_query_defaults_on`.

## 6. Catalog

Mỗi metric trong `/semantic-catalog` có `query_defaults` (hoặc `null`):

```json
"query_defaults": {
  "grain": "day", "row_kind_column": "loai_quan_sat", "row_kind_value": "DU_BAO_NGAY", "native_grain": "day",
  "time_column": "thoi_diem_quan_sat", "time_window": "last_7_day", "time_anchor": "latest_data",
  "default_filters": [{"column": "thanh_pho_key", "operator": "IN", "value": [1, 2]}]
}
```

## 7. Thực thi

Body của `.../semantic-query/execute` nhận thêm `time_grain` và `apply_defaults` (mặc định `true`). Khi có khai báo và
`apply_defaults` khác `false`:

1. Loại dòng thành bộ lọc `row_kind_column == row_kind_value`, trừ khi người gọi lọc cột phân loại.
2. Mỗi bộ lọc mặc định được thêm, trừ khi người gọi lọc chính cột đó.
3. Khoảng thời gian được thêm thành `>= đầu` và `< cuối` (`<=` mốc tính với `<đơn vị>_to_date`), trừ khi người gọi lọc
   cột thời gian. `last_7_day` là ngày chứa mốc tính và sáu ngày trước; tuần bắt đầu thứ Hai. Mốc `latest_data` là
   `MAX(cột thời gian)` dưới bộ lọc loại dòng và bộ lọc mặc định, đọc qua ChartData; không đọc được thì tính từ hiện tại.
4. Khi người gọi chia theo cột thời gian của metric, cột đó được gom theo grain (cột `BASE_AXIS` có `timeGrain` `PT1H`,
   `P1D`, `P1W`, `P1M`, `P3M`, `P1Y`). `time_grain` của người gọi thay grain này nhưng không được mịn hơn grain gốc, và
   cần cột thời gian của metric trong `dimensions`.

Mỗi giá trị lọc, của người gọi hay mặc định, phải hợp kiểu cột: cột ngày hoặc ngày giờ nhận `YYYY-MM-DD` hoặc
`YYYY-MM-DD HH:MM:SS` (có thể kèm phần giây lẻ và múi giờ), cột số nhận số, kể cả cột ngày lưu dạng epoch số. Giá trị sai
kiểu bị từ chối với 400 và thông báo nêu cột, trước khi truy vấn tới database.

Kết quả có `applied_defaults`: `filters` (mỗi bộ lọc kèm `source`: `row_kind`, `default`, `time_window`), `time_window`
(khoảng đã dùng, mốc tính) và `time_grain`. Cách viết `BASE_AXIS` cần xác nhận bằng `scripts/compat.py` và
`scripts/smoke.py` sau khi triển khai.

## 8. Giao diện

Thẻ Định nghĩa của màn Metric có mục "Grain, mốc thời gian và bộ lọc mặc định": xem và sửa loại dòng, grain, cột thời
gian, khoảng thời gian (loại, số đơn vị, đơn vị, mốc tính) và bộ lọc mặc định. Thẻ Chạy thử có ô "Áp dụng … mặc định
của metric" và hiện những gì đã áp dụng.

## 9. AI Agent

- Metric trong catalog mang `query_defaults` (bỏ phần trống) vào prompt `understand_question`. Prompt dặn: câu hỏi không
  nêu khoảng thời gian thì không thêm bộ lọc `time`; không chép lại bộ lọc mặc định; chỉ đặt `time_grain` khi câu hỏi
  chia thời gian theo đơn vị khác grain của metric.
- `plan_query` chỉ gửi `time_grain` khi mọi metric được chia theo cột thời gian của chính nó; grain mịn hơn dữ liệu được
  nâng lên grain gốc kèm ghi chú ("… chỉ có số liệu theo ngày, nên kết quả được tính theo ngày.").
- `applied_defaults` của mỗi metric thành `defaults` của kết quả; khoảng thời gian mặc định thêm một ghi chú nêu khoảng
  đã dùng, để câu trả lời nói rõ.

## 10. Kiểm thử

- `tests/test_metric_query_defaults.py` (Semantic Layer): kiểm tra khi lưu, khoảng thời gian, áp dụng và ghi đè khi
  chạy, `apply_defaults`, `time_grain`, mốc `latest_data`, hash và trạng thái `outdated`.
- `tests/test_semantic_query_routes.py`, `tests/test_semantic_catalog.py`: route lưu, danh sách metric, catalog.
- `tests/test_query_extensions.py` (AI Agent): `time_grain`, ghi chú grain, `defaults` của kết quả.
