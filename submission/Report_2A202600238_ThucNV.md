# Báo cáo Thực hành CI/CD cho Hệ thống AI

**1. Bộ siêu tham số đã chọn và lý do**

- **n_estimators:** 200
- **max_depth:** 20
- **min_samples_split:** 2
- **Lý do lựa chọn:** Ban đầu, khi sử dụng cấu hình mặc định, mô hình chỉ đạt độ chính xác tương đối thấp (khoảng ~0.64). Để có thể vượt qua mốc yêu cầu của hệ thống (Eval Accuracy >= 0.70), em đã xây dựng một script áp dụng thuật toán Grid Search để chạy tự động và duyệt qua hàng trăm cấu hình siêu tham số khác nhau. Tổ hợp `(200, 20, 2)` được lựa chọn vì nó gia tăng tối đa khả năng học sâu và phân nhánh của cây quyết định mà vẫn giữ được tính tổng quát, đem lại kết quả chính xác cao nhất cho tập dữ liệu đánh giá hiện tại.

**2. Các khó khăn gặp phải và cách giải quyết**

Trong quá trình xây dựng toàn bộ quy trình CI/CD và triển khai thực tế trên hệ thống Cloud, em đã gặp phải một số trở ngại và đã khắc phục như sau:

- **Cài đặt nhầm phiên bản DVC (không hỗ trợ lưu trữ S3):**
  - *Khó khăn:* Ban đầu chỉ cài đặt bằng lệnh `pip install dvc` thông thường, dẫn đến việc DVC báo lỗi không hiểu cú pháp đường dẫn S3 khi pull/push dữ liệu do bài lab yêu cầu dùng hệ thống AWS thay cho GCP.
  - *Cách giải quyết:* Đã gỡ phiên bản DVC cơ bản và cài đặt lại gói bổ trợ thông qua lệnh `pip install dvc[s3]` để tích hợp hoàn chỉnh với AWS S3.

- **Tốn quá nhiều thời gian để tinh chỉnh bộ siêu tham số thủ công:**
  - *Khó khăn:* Quá trình tinh chỉnh siêu tham số để mô hình đạt mức accuracy > 0.70 mất rất nhiều thời gian nếu chỉ thử nghiệm bằng tay từng bộ số trong `params.yaml`.
  - *Cách giải quyết:* Em đã viết một kịch bản Python riêng (`search_params.py`) áp dụng kỹ thuật tìm kiếm lưới (Grid Search) để tự động hóa hoàn toàn quá trình huấn luyện và đánh giá trên tập `eval.csv`, sau đó tự động lưu cấu hình tốt nhất vào lại file `params.yaml`.

- **Không thể kết nối SSH vào máy ảo (VM) EC2:**
  - *Khó khăn:* Gặp lỗi từ chối quyền truy cập (Permission denied) khi thử SSH vào server do file khóa (Private Key `.pem`) có cấp độ quyền không an toàn trên máy trạm.
  - *Cách giải quyết:* Sử dụng lệnh `chmod 400 <tên_file>.pem` để giới hạn chặt chẽ lại phân quyền của file khóa, đáp ứng tiêu chuẩn bảo mật của AWS.

- **Lỗi Pipeline GitHub Actions khi thực thi Unit Test:**
  - *Khó khăn:* Khi đẩy code lên GitHub, tiến trình Action chạy bị fail liên tục do Unit test chưa hoàn thiện. Thêm vào đó, lúc đầu do thiếu kinh nghiệm nên không biết check log ở đâu và cấu hình sai bộ lọc thư mục `paths`, khiến các bản vá lỗi không kích hoạt được workflow chạy lại.
  - *Cách giải quyết:* Tiến hành kiểm tra trực tiếp tab "Actions", bổ sung thêm các đường dẫn mở rộng (như `tests/**`, `requirements.txt`) vào mục `paths` ở trong file cấu hình `.github/workflows/mlops.yml` để mỗi khi file test được chỉnh sửa, hệ thống CI/CD đều tự động chạy lại ngay lập tức.

- **Lỗi ghi nhận tiến trình với MLflow:**
  - *Khó khăn:* Gặp lỗi crash `MlflowException: Could not find experiment with ID 0` trong quá trình khởi tạo MLflow khi tiến hành huấn luyện.
  - *Cách giải quyết:* Đã bổ sung thêm đoạn code gọi hàm `mlflow.set_experiment("random_forest_training")` trước khi thực thi khối lệnh `with mlflow.start_run():`, giúp MLflow đăng ký và nhận diện đúng không gian thí nghiệm để theo dõi các metric và artifact.

- **Môi trường Cloud khác biệt (Sử dụng AWS thay cho GCP):**
  - *Khó khăn:* Tài liệu gốc của bài lab tập trung vào Google Cloud Platform (dùng lệnh `gcloud`, `gsutil`, phân quyền qua tệp JSON), trong khi hệ thống của em triển khai 100% trên Amazon Web Services, gây bỡ ngỡ trong việc ánh xạ cấu hình.
  - *Cách giải quyết:* Đã tự động thay đổi cú pháp CLI tương ứng. Điển hình là trong Workflow Job, thay vì `gsutil cp`, em dùng `aws s3 cp` để đồng bộ model. Em cũng đã dùng bash script tích hợp sẵn mã python nội tuyến (inline python) để trích xuất Access Key (AK/SK) từ Secret của GitHub nhằm nạp vào biến môi trường hệ thống cho các CLI AWS chạy mượt mà.
