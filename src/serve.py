from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import boto3
import joblib
import os

app = FastAPI()

# Read the BUCKET variable instead of GCS_BUCKET
S3_BUCKET = os.environ.get("BUCKET", "data-vthucs")
S3_MODEL_KEY = "models/latest/model.pkl"
MODEL_PATH = os.path.expanduser("~/models/model.pkl")


def download_model():
    """
    Tai file model.pkl tu S3 ve may khi server khoi dong.

    Ham nay duoc goi mot lan khi module duoc import. Su dung
    AWS_ACCESS_KEY_ID va AWS_SECRET_ACCESS_KEY de xac thuc.
    """
    # TODO 1: Tao S3 client bang boto3
    s3_client = boto3.client('s3')

    # TODO 2 & 3: Tai file model xuong may tu S3
    s3_client.download_file(S3_BUCKET, S3_MODEL_KEY, MODEL_PATH)

    # TODO 4: In thong bao thanh cong
    print("Model da duoc tai xuong tu AWS S3.")


download_model()
model = joblib.load(MODEL_PATH)


class PredictRequest(BaseModel):
    features: list[float]


@app.get("/health")
def health():
    """
    Endpoint kiem tra suc khoe server.
    GitHub Actions goi endpoint nay sau khi deploy de xac nhan server dang chay.

    Tra ve: {"status": "ok"}
    """
    # TODO 5: Tra ve dict {"status": "ok"}
    return {"status": "ok"}


@app.post("/predict")
def predict(req: PredictRequest):
    """
    Endpoint suy luan chinh.

    Dau vao : JSON {"features": [f1, f2, ..., f12]}
    Dau ra  : JSON {"prediction": <0|1|2>, "label": <"thap"|"trung_binh"|"cao">}

    Thu tu 12 dac trung (khop voi thu tu trong FEATURE_NAMES cua test):
        fixed_acidity, volatile_acidity, citric_acid, residual_sugar,
        chlorides, free_sulfur_dioxide, total_sulfur_dioxide, density,
        pH, sulphates, alcohol, wine_type
    """
    # TODO 6: Kiem tra so luong dac trung.
    if len(req.features) != 12:
        raise HTTPException(status_code=400, detail="Vui long cung cap dung 12 dac trung")

    # TODO 7: Goi model.predict([req.features]) de lay ket qua du doan.
    pred = model.predict([req.features])[0]

    # TODO 8: Tra ve dict chua "prediction" (int) va "label" (string).
    label_map = {0: "thap", 1: "trung_binh", 2: "cao"}
    return {
        "prediction": int(pred),
        "label": label_map.get(int(pred), "khong_xac_dinh")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
