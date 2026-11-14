# Sửa lỗi Data Dictionary và relationship contract

## Hành vi sau sửa

- Áp dụng gợi ý thay đích kiểm tra contract cũ trước khi đổi khóa hoặc cột đích. Contract đang approved trả 409, yêu
  cầu thu hồi trước; không chụp đè bản duyệt thành candidate theo đích mới.
- Recheck không đạt đưa contract về candidate, xóa người/thời điểm duyệt. Nếu truy vấn warehouse lỗi, cũng vô hiệu
  hóa và commit việc bỏ duyệt trước khi trả 500. AI Agent chỉ nhận quan hệ approved còn khớp hash và có kết quả kiểm
  tra hiện tại đạt; không dùng bằng chứng cũ hoặc không đạt.
- Thu hồi chỉ nhận approved. Duyệt áp dụng `TEXT_TO_BI_REQUIRE_SECOND_REVIEWER`; người soạn candidate không tự duyệt
  khi bật quy tắc. Khi chụp lại candidate, `owner_id` là người soạn bản mới.
- PUT từ điển luôn kiểm tra ngữ nghĩa thời gian sau cập nhật cột, kể cả khi body không sửa thông tin dataset. Không
  được xóa temporal_kind của time_column đang chọn; có thể đồng thời bỏ time_column và các thiết lập phụ thuộc.
- GET dictionary, danh sách quan hệ, schema graph và xuất file không seed. Snapshot kết hợp metadata đã lưu với
  mặc định tạm cho cột còn thiếu, không thêm object vào session; cột chưa lưu có ID null. Preview file cũng không
  seed, có rollback_on_error. Migration gate khởi tạo bảng trên lần truy cập đầu vẫn theo quy ước chung.
- Chỉ suggest=1 bật gợi ý; bool không hợp lệ cho to_dataset_id; lỗi temporal_kind gọi đúng tham số; Viewer nhận
  read_only=true. Frontend chấp nhận ID null và dùng tên cột cho vùng mở rộng chi tiết.
- AutoFill lấy PostgreSQL advisory lock trên connection riêng trước khi seed. Khóa tồn tại qua các commit của
  stream, dùng chung giữa worker; không có TTL mở khóa khi lượt cũ còn chạy. Đóng stream, đóng response hoặc lỗi
  chuẩn bị đều nhả khóa; PostgreSQL tự nhả khi connection của worker chết. Engine khác PostgreSQL trả 503.

## Kiểm chứng

- 24 test hồi quy mới; tổng nhóm kiểm tra liên quan và AI Agent: 204 test đạt.
- Ruff phần sửa và TypeScript typecheck đạt. Compile/import backend trên Superset/Python 3.10 đạt.
- Khóa AutoFill được thử bằng hai session PostgreSQL độc lập: khóa cùng dataset bị từ chối, lấy lại được sau khi nhả.
- Snapshot dataset chưa seed được serialize với ORM thật: không DML, không object pending trong session và
  read_only=true trong ngữ cảnh không phải admin.
- 13 endpoint smoke hiện có đạt. Các kiểm tra API bổ sung xác nhận suggest=0/1, temporal_kind sai, ID bool, export
  và preview; không chạy AutoFill gọi model hay thay trạng thái quan hệ thật để thử lỗi.
- Bộ test Semantic Layer đầy đủ vẫn bị chặn bởi 19 lỗi import đường dẫn module cũ của đợt refactor trước đó; không
  coi toàn bộ suite đã đạt.
