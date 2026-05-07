# Bước 2 - Pipeline CI/CD Tự Động

Mục tiêu: Mỗi khi bạn push code hoặc thay đổi dữ liệu, GitHub Actions tự động huấn luyện mô hình, kiểm tra accuracy có đạt ngưỡng >= 0.70 không, và triển khai lên VM nếu đạt yêu cầu.

Thời gian ước tính: 4-5 giờ

---

## Lựa Chọn Cloud Provider

Bạn có thể sử dụng **một trong ba** cloud provider sau. Các hướng dẫn trong file này lấy **GCP làm ví dụ mặc định**. Nếu dùng AWS hoặc Azure, ánh xạ theo bảng dưới đây:

| Khái niệm | GCP | AWS | Azure |
|---|---|---|---|
| Object Storage | Google Cloud Storage (GCS) | Amazon S3 | Azure Blob Storage |
| VM | Compute Engine (GCE) | EC2 | Azure Virtual Machine |
| CLI | `gcloud` / `gsutil` | `aws` | `az` |
| DVC storage extra | `dvc[gs]` | `dvc[s3]` | `dvc[azure]` |
| Cloud SDK Python | `google-cloud-storage` | `boto3` | `azure-storage-blob` |
| Credentials | Service Account JSON | Access Key / IAM Role | Service Principal / Connection String |

---

## 2.1 Tạo Cloud Storage Bucket

Tên bucket phải là duy nhất trên toàn bộ hệ thống của provider đã chọn. Ví dụ dưới đây dùng GCP — thay bằng lệnh tương đương nếu dùng AWS (`aws s3 mb s3://$BUCKET`) hoặc Azure (`az storage container create --name $CONTAINER`).

Thay thế `<YOUR_PROJECT>` và `<BUCKET_NAME>` bằng giá trị của bạn.

```bash
export PROJECT=<YOUR_PROJECT>
export BUCKET=<BUCKET_NAME>

gsutil mb -p $PROJECT -l us-central1 gs://$BUCKET
```

Kích hoạt Cloud Storage API (chỉ cần làm một lần):

```bash
gcloud services enable storage.googleapis.com --project $PROJECT
```

---

## 2.2 Tạo Cloud Credentials

Mỗi provider có cơ chế xác thực riêng: GCP dùng Service Account JSON, AWS dùng IAM User Access Key hoặc IAM Role, Azure dùng Service Principal hoặc Connection String. Ví dụ dưới đây dùng GCP.

Service account này là danh tính duy nhất được phép truy cập bucket. Nguyên tắc quyền tối thiểu: chỉ cấp quyền cần thiết, trên đúng phạm vi cần thiết.

| Role | Sử dụng | Lý do |
|---|---|---|
| roles/storage.objectAdmin | Nên dùng | Cho phép đọc, ghi, xóa object bên trong bucket. DVC cần quyền này. |
| roles/storage.admin | Không dùng | Cho phép xóa cả bucket, vi phạm nguyên tắc quyền tối thiểu. |

```bash
# Tạo service account
gcloud iam service-accounts create mlops-lab-sa \
  --display-name "MLOps Lab SA" \
  --project $PROJECT

# Cấp quyền objectAdmin chỉ trên bucket của bạn (không phải toàn bộ project)
gsutil iam ch \
  serviceAccount:mlops-lab-sa@$PROJECT.iam.gserviceaccount.com:roles/storage.objectAdmin \
  gs://$BUCKET

# Xuất file key JSON
gcloud iam service-accounts keys create sa-key.json \
  --iam-account mlops-lab-sa@$PROJECT.iam.gserviceaccount.com
```

Lưu ý: `sa-key.json` tuyệt đối không được commit vào git. File này đã có trong `.gitignore`.

---

## 2.3 Cài Đặt DVC Với Cloud Storage Remote

```bash
dvc init

# Trỏ DVC đến cloud storage (chọn một dòng theo provider):
# GCP:   dvc remote add -d myremote gs://$BUCKET/dvc
# AWS:   dvc remote add -d myremote s3://$BUCKET/dvc
# Azure: dvc remote add -d myremote azure://mycontainer/dvc
dvc remote add -d myremote gs://$BUCKET/dvc   # thay URL theo provider

# Cấu hình credentials:
# GCP: thêm đường dẫn service account key
dvc remote modify myremote credentialpath sa-key.json
# AWS: tự đọc ~/.aws/credentials hoặc biến môi trường AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
# Azure: dvc remote modify myremote connection_string "<YOUR_CONNECTION_STRING>"

# Theo dõi các file dữ liệu bằng DVC
dvc add data/train_phase1.csv
dvc add data/eval.csv
dvc add data/train_phase2.csv

# Commit các file con trỏ DVC vào git (KHÔNG phải file CSV)
git add data/train_phase1.csv.dvc data/eval.csv.dvc data/train_phase2.csv.dvc \
        .gitignore .dvc/config
git commit -m "feat: track datasets with DVC"

# Đẩy các file CSV lên GCS
dvc push
```

Xác nhận trên Cloud Storage Console rằng các file dữ liệu đã xuất hiện dưới prefix `dvc/` trong bucket.

---

## 2.4 Tạo VM Trên Cloud

Ví dụ dưới đây dùng GCE (GCP). Tương đương: AWS EC2 (`aws ec2 run-instances ...`) hoặc Azure VM (`az vm create ...`). Sau khi tạo, lấy IP công khai để dùng cho GitHub Secrets.

```bash
gcloud compute instances create mlops-serve \
  --zone=us-central1-a \
  --machine-type=e2-small \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --tags=mlops-serve \
  --project $PROJECT

# Mở cổng 8000 cho inference API
gcloud compute firewall-rules create allow-mlops-serve \
  --allow=tcp:8000 \
  --target-tags=mlops-serve \
  --project $PROJECT

# Lấy IP công khai của VM (lưu lại, cần dùng cho GitHub Secrets)
gcloud compute instances describe mlops-serve \
  --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

---

## 2.5 Cấu Hình VM (Thực Hiện Một Lần, Thủ Công)

SSH vào VM:

```bash
gcloud compute ssh mlops-serve --zone=us-central1-a
```

Bên trong VM, cài đặt các thư viện cần thiết:

```bash
sudo apt update && sudo apt install -y python3-pip
pip3 install fastapi uvicorn scikit-learn joblib google-cloud-storage

mkdir -p ~/models ~/src
```

Thoát khỏi VM, sau đó copy file key lên VM:

```bash
gcloud compute scp sa-key.json mlops-serve:~/sa-key.json \
  --zone=us-central1-a
```

---

## 2.6 Viết `src/serve.py`

Tạo file `src/serve.py` theo khung dưới đây. File này chạy trên VM và cung cấp REST API để nhận yêu cầu suy luận.

Nhiệm vụ:
1. Khi khởi động, tải file `model.pkl` từ GCS về máy.
2. Cung cấp endpoint `GET /health` trả về trạng thái server.
3. Cung cấp endpoint `POST /predict` nhận 12 đặc trưng và trả về nhãn dự đoán.

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
# Cloud SDK: google-cloud-storage (GCP) | boto3 (AWS) | azure-storage-blob (Azure)
from google.cloud import storage   # thay bằng SDK của provider đã chọn
import joblib
import os

app = FastAPI()

# Đọc tên bucket từ biến môi trường (được đặt trong systemd service)
GCS_BUCKET = os.environ["GCS_BUCKET"]
GCS_MODEL_KEY = "models/latest/model.pkl"
MODEL_PATH = os.path.expanduser("~/models/model.pkl")


def download_model():
    """Tải file model.pkl từ GCS về máy khi server khởi động."""
    # TODO 2.6.1: Tạo một storage.Client()
    # TODO 2.6.2: Lấy bucket bằng client.bucket(GCS_BUCKET)
    # TODO 2.6.3: Lấy blob bằng bucket.blob(GCS_MODEL_KEY)
    # TODO 2.6.4: Tải file xuống bằng blob.download_to_filename(MODEL_PATH)
    # TODO 2.6.5: In thông báo thành công
    pass  # xóa dòng này khi đã viết xong


# Gọi hàm này khi module được import (chạy khi server khởi động)
download_model()
model = joblib.load(MODEL_PATH)


class PredictRequest(BaseModel):
    features: list[float]


@app.get("/health")
def health():
    """Endpoint kiểm tra sức khỏe server. GitHub Actions dùng endpoint này để xác nhận deploy thành công."""
    # TODO 2.6.6: Trả về dict {"status": "ok"}
    pass  # xóa dòng này khi đã viết xong


@app.post("/predict")
def predict(req: PredictRequest):
    """
    Endpoint suy luận.

    Đầu vào: JSON {"features": [f1, f2, ..., f12]}
    Đầu ra:  JSON {"prediction": <0|1|2>, "label": <"thấp"|"trung_bình"|"cao">}
    """
    # TODO 2.6.7: Kiểm tra len(req.features) == 12.
    #   Nếu không, raise HTTPException(status_code=400, detail="Expected 12 features (wine quality)")

    # TODO 2.6.8: Gọi model.predict([req.features]) để lấy kết quả dự đoán.

    # TODO 2.6.9: Trả về dict chứa "prediction" (int) và "label" (string).
    #   Nhãn: 0 -> "thấp", 1 -> "trung_bình", 2 -> "cao"
    pass  # xóa dòng này khi đã viết xong


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

Upload file `serve.py` len VM:

```bash
gcloud compute scp src/serve.py mlops-serve:~/src/serve.py \
  --zone=us-central1-a
```

---

## 2.7 Cau Hinh Systemd Service Tren VM

SSH tro lai vao VM:

```bash
gcloud compute ssh mlops-serve --zone=us-central1-a
```

Tao file service de server tu dong khoi dong lai khi VM reboot:

```bash
sudo tee /etc/systemd/system/mlops-serve.service > /dev/null <<EOF
[Unit]
Description=MLOps Model Inference Server
After=network.target

[Service]
User=$USER
WorkingDirectory=/home/$USER
Environment="GCS_BUCKET=<YOUR_BUCKET_NAME>"
Environment="GOOGLE_APPLICATION_CREDENTIALS=/home/$USER/sa-key.json"
ExecStart=/usr/bin/python3 /home/$USER/src/serve.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable mlops-serve
```

Thay `<YOUR_BUCKET_NAME>` bang ten bucket thuc su cua ban truoc khi chay.

Chua can khoi dong service luc nay. Model chua co tren GCS cho den khi pipeline CI/CD chay lan dau tien.

---

## 2.8 Tao SSH Key De GitHub Actions Deploy

Chay tren may tinh ca nhan (khong phai VM):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mlops_deploy -N "" -C "github-actions-deploy"
```

Them public key vao VM:

```bash
gcloud compute ssh mlops-serve --zone=us-central1-a \
  --command "echo '$(cat ~/.ssh/mlops_deploy.pub)' >> ~/.ssh/authorized_keys"
```

---

## 2.9 Them GitHub Secrets

Vao repo GitHub: Settings > Secrets and variables > Actions > New repository secret.

Them chinh xac 5 secrets sau:

| Ten secret | Cach lay gia tri |
|---|---|
| CLOUD_CREDENTIALS | GCP: toàn bộ nội dung `sa-key.json` (JSON). AWS: `{"aws_access_key_id":"...","aws_secret_access_key":"..."}`. Azure: Connection String. |
| CLOUD_BUCKET | Tên bucket / container (ví dụ: `my-mlops-bucket`) |
| VM_HOST | IP cong khai cua VM (tu buoc 2.4) |
| VM_USER | Ten user tren VM (chay `echo $USER` trong session SSH tren VM) |
| VM_SSH_KEY | Dan toan bo noi dung `~/.ssh/mlops_deploy` (private key, bat dau bang `-----BEGIN OPENSSH PRIVATE KEY-----`) |

Kiem tra: Moi secret khi dan vao phai khong co khoang trang o dau hoac cuoi.

---

## 2.10 Viet `tests/test_train.py`

Cac test nay chay tren du lieu nho tao trong bo nho (khong can pull DVC), dam bao chay duoc trong GitHub Actions ma khong can xac thuc GCS.

Tao file `tests/test_train.py` theo khung duoi day:

```python
import os
import json
import numpy as np
import pandas as pd
from src.train import train


FEATURE_NAMES = [
    "fixed_acidity", "volatile_acidity", "citric_acid", "residual_sugar",
    "chlorides", "free_sulfur_dioxide", "total_sulfur_dioxide", "density",
    "pH", "sulphates", "alcohol", "wine_type",
]


def _make_temp_data(tmp_path):
    """
    Tao dataset nho voi cung schema Wine Quality de su dung trong test.

    pytest cung cap `tmp_path` la mot thu muc tam thoi, tu dong duoc xoa sau khi test ket thuc.
    """
    rng = np.random.default_rng(0)
    n = 200
    # TODO 2.10.1: Tao mang X co kich thuoc (n, len(FEATURE_NAMES)) voi gia tri ngau nhien [0, 1)
    # TODO 2.10.2: Tao mang y co n phan tu, moi phan tu la so nguyen ngau nhien trong [0, 3)
    # TODO 2.10.3: Tao DataFrame tu X voi cac cot la FEATURE_NAMES, them cot "target" = y
    # TODO 2.10.4: Luu 160 dong dau vao file train.csv va 40 dong cuoi vao file eval.csv tai tmp_path
    # TODO 2.10.5: Tra ve (train_path, eval_path)
    pass  # xoa dong nay khi da viet xong


def test_train_returns_float(tmp_path):
    """Kiem tra ham train() tra ve mot so thuc trong khoang [0, 1]."""
    train_path, eval_path = _make_temp_data(tmp_path)
    # TODO 2.10.6: Goi ham train() voi sieu tham so nho (n_estimators=10, max_depth=3)
    # TODO 2.10.7: assert ket qua tra ve la float va nam trong [0.0, 1.0]
    pass  # xoa dong nay khi da viet xong


def test_metrics_file_created(tmp_path):
    """Kiem tra file outputs/metrics.json duoc tao sau khi huan luyen."""
    train_path, eval_path = _make_temp_data(tmp_path)
    train(
        {"n_estimators": 10, "max_depth": 3},
        data_path=train_path,
        eval_path=eval_path,
    )
    # TODO 2.10.8: assert file "outputs/metrics.json" ton tai
    # TODO 2.10.9: Doc file metrics.json va assert no chua ca "accuracy" va "f1_score"
    pass  # xoa dong nay khi da viet xong


def test_model_file_created(tmp_path):
    """Kiem tra file models/model.pkl duoc tao sau khi huan luyen."""
    train_path, eval_path = _make_temp_data(tmp_path)
    train(
        {"n_estimators": 10, "max_depth": 3},
        data_path=train_path,
        eval_path=eval_path,
    )
    # TODO 2.10.10: assert file "models/model.pkl" ton tai
    pass  # xoa dong nay khi da viet xong
```

Chay thu test cuc bo truoc khi commit:

```bash
pytest tests/ -v
```

Ba test deu phai qua truoc khi tiep tuc.

---

## 2.11 Viet `.github/workflows/mlops.yml`

Pipeline gồm bốn jobs chạy theo thứ tự: Unit Test -> Train -> Eval -> Deploy.

Tao file `.github/workflows/mlops.yml` theo khung duoi day:

```yaml
name: MLOps Pipeline

on:
  push:
    branches: [main]
    paths:
      - 'data/**.dvc'
      - 'src/**.py'
      - 'params.yaml'
  workflow_dispatch:

jobs:

  # JOB 1: Chay unit tests tren du lieu ao (khong can GCS)
  test:
    name: Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        # TODO 2.11.1: Chay pytest tren thu muc tests/ voi co -v
        run: # <dien lenh o day>

  # JOB 2: Huan luyen mo hinh tren du lieu thuc, upload artifact len cloud storage
  train:
    name: Train
    needs: test              # Chi chay khi job test qua
    runs-on: ubuntu-latest
    outputs:
      accuracy: ${{ steps.read_metrics.outputs.accuracy }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Authenticate to Cloud Storage
        # TODO 2.11.2: Ghi noi dung secret CLOUD_CREDENTIALS ra file tam
        #   va set bien moi truong xac thuc tuong ung:
        #   GCP: GOOGLE_APPLICATION_CREDENTIALS=/tmp/sa-key.json
        #   AWS: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
        #   Azure: AZURE_STORAGE_CONNECTION_STRING
        run: |
          # <dien code o day>

      - name: Pull data with DVC
        # TODO 2.11.3: Dung lenh dvc pull de tai train_phase1.csv va eval.csv tu cloud storage
        run: # <dien lenh o day>

      - name: Train model
        run: python src/train.py

      - name: Read metrics
        id: read_metrics
        # TODO 2.11.4: Doc gia tri "accuracy" tu file outputs/metrics.json
        #   va set no thanh output "accuracy" de job deploy co the doc duoc.
        #   Goi y: su dung python -c "..." va echo "accuracy=..." >> $GITHUB_OUTPUT
        run: |
          # <dien code o day>

      - name: Upload model to Cloud Storage
        # TODO 2.11.5: Su dung google-cloud-storage SDK de upload
        #   file models/model.pkl len gs://<bucket>/models/latest/model.pkl
        run: |
          python - <<'EOF'
          # <dien code Python o day>
          EOF

      - name: Save metrics as artifact
        uses: actions/upload-artifact@v4
        with:
          name: metrics
          path: outputs/metrics.json

  # JOB 3: Kiem tra chat luong - chi cho phep deploy khi accuracy >= 0.70
  eval:
    name: Eval
    needs: train             # Chi chay khi job train qua
    runs-on: ubuntu-latest
    steps:

      - name: Check eval gate
        # TODO 2.11.6: Doc gia tri accuracy tu output cua job train.
        #   Neu accuracy < 0.70, ket thuc voi loi (SystemExit hoac exit 1).
        #   Neu dat, in thong bao va tiep tuc.
        run: |
          python - <<'EOF'
          # <dien code Python o day>
          EOF

  # JOB 4: Trien khai sau khi eval gate qua
  deploy:
    name: Deploy
    needs: eval              # Chi chay khi job eval qua
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VM_HOST }}
          username: ${{ secrets.VM_USER }}
          key: ${{ secrets.VM_SSH_KEY }}
          script: |
            # TODO 2.11.7: Restart service mlops-serve tren VM.
            # TODO 2.11.8: Cho server san sang (sleep 5 giay) roi goi curl /health de xac nhan.
            #   Neu health check that bai, thoat voi exit 1.
            # <dien lenh bash o day>
```

---

## 2.12 Lan Chay Pipeline Dau Tien

Tao hai file con trong `src/` va `tests/` de Python co the import module:

```bash
touch src/__init__.py tests/__init__.py
```

Push tat ca len GitHub:

```bash
git add .
git commit -m "feat: add CI/CD pipeline, tests, and serving API"
git push origin main
```

Theo doi pipeline trong tab **Actions** tren repo GitHub.

Sau khi pipeline chay thanh cong va model da duoc upload len cloud storage, khoi dong service tren VM:

```bash
gcloud compute ssh mlops-serve --zone=us-central1-a \
  --command "sudo systemctl start mlops-serve"
```

Thu nghiem endpoint:

```bash
VM_IP=<YOUR_VM_IP>

# Kiem tra suc khoe
curl http://$VM_IP:8000/health

# Du doan (12 dac trung theo thu tu trong FEATURE_NAMES)
curl -X POST http://$VM_IP:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"features": [7.4, 0.70, 0.00, 1.9, 0.076, 11.0, 34.0, 0.9978, 3.51, 0.56, 9.4, 0]}'
```

Ket qua mong doi:

```json
{"prediction": 0, "label": "thap"}
```

---

## Xu Ly Su Co

**`dvc push` that bai voi loi xac thuc**

Xac nhan `sa-key.json` ton tai va `credentialpath` da duoc dat dung. Kiem tra bang:

```bash
cat .dvc/config
```

Neu chua co muc `credentialpath`, chay lai:

```bash
dvc remote modify myremote credentialpath sa-key.json
```

**GitHub Actions `dvc pull` that bai**

Secret `CLOUD_CREDENTIALS` phải là toàn bộ nội dung JSON (GCP) hoặc chuỗi tương đương của provider. Mở secret trong GitHub Settings và xác nhận nội dung hợp lệ.

**Job Deploy thất bại dù accuracy có vẻ đủ cao**

GitHub Actions outputs là kiểu chuỗi. Đảm bảo code Python trong eval gate thực hiện chuyển đổi `float()` trước khi so sánh. Kiểm tra giá trị accuracy được in trong log của job Train.

**Service trên VM không khởi động được**

Xem log của service:

```bash
sudo journalctl -u mlops-serve -n 50
```

Nguyên nhân phổ biến:
- Biến môi trường `CLOUD_BUCKET` sai trong file service.
- `sa-key.json` chưa được copy lên VM.
- File model chưa tồn tại trên GCS (service chỉ có thể khởi động sau khi pipeline lần đầu tiên chạy thành công).

---

## Kết Quả Cần Đạt - Bước 2

- Cả bốn GitHub Actions jobs (Unit Test, Train, Eval, Deploy) đều hoàn thành thành công (màu xanh).
- `curl http://VM_IP:8000/health` trả về `{"status": "ok"}`.
- `curl http://VM_IP:8000/predict` trả về kết quả dự đoán hợp lệ.
- GCS Console hiển thị file dữ liệu dưới `dvc/` và file model dưới `models/latest/model.pkl`.

Chụp màn hình tab Actions hiển thị cả bốn jobs màu xanh (cần nộp bài).

---

Tiếp theo: [Bước 3 - Huấn luyện liên tục](buoc-3.md)
