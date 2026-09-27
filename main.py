import base64
import json
import cv2
import numpy as np
import uuid
import os
from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from database import engine, get_db, Base
from models import User, KYCRequest, VerificationDocument, FraudLog, KYCStatus, DocumentType, FraudRiskLevel
import easyocr
from deepface import DeepFace

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Enterprise KYC System")

SECRET_KEY_BYTES = b"12345678901234567890123456789012"

print("--> Loading AI Models (OCR)...")
ocr_reader = easyocr.Reader(['ar', 'en'], gpu=False)
print("--> AI Models Loaded!")

class EncryptedKYCPayload(BaseModel):
    user_id: str
    ciphertext_base64: str
    nonce_base64: str

def decrypt_payload(ciphertext_b64: str, nonce_b64: str) -> dict:
    try:
        aesgcm = AESGCM(SECRET_KEY_BYTES)
        ciphertext = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(decrypted_bytes.decode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"فشل فك التشفير: {str(e)}")

def process_image_opencv(cv2_img):
    gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
    
    f = np.fft.fft2(gray)
    fshift = np.fft.fftshift(f)
    magnitude_spectrum = 20 * np.log(np.abs(fshift) + 1)
    mean_freq = np.mean(magnitude_spectrum)
    is_screen = bool(mean_freq > 145.0)

    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    is_blurry = bool(laplacian_var < 80.0)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    binarized = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10)

    return {"binarized_img": binarized, "is_screen": is_screen, "is_blurry": is_blurry, "blur_score": laplacian_var, "fft_score": mean_freq}

@app.post("/api/v1/kyc/process-full-verification/", status_code=status.HTTP_201_CREATED)
async def process_kyc(payload: EncryptedKYCPayload, db: Session = Depends(get_db)):
    data = decrypt_payload(payload.ciphertext_base64, payload.nonce_base64)
    id_number = data.get("id_number")
    id_card_b64 = data.get("id_card_image_base64")
    selfie_b64 = data.get("selfie_image_base64")

    id_bytes = base64.b64decode(id_card_b64)
    selfie_bytes = base64.b64decode(selfie_b64)
    id_img = cv2.imdecode(np.frombuffer(id_bytes, np.uint8), cv2.IMREAD_COLOR)
    selfie_img = cv2.imdecode(np.frombuffer(selfie_bytes, np.uint8), cv2.IMREAD_COLOR)

    vision_res = process_image_opencv(id_img)
    ocr_res = ocr_reader.readtext(vision_res["binarized_img"], detail=0)

    temp_id = f"/tmp/id_{uuid.uuid4().hex}.jpg"
    temp_selfie = f"/tmp/selfie_{uuid.uuid4().hex}.jpg"
    cv2.imwrite(temp_id, id_img)
    cv2.imwrite(temp_selfie, selfie_img)

    try:
        df_res = DeepFace.verify(img1_path=temp_id, img2_path=temp_selfie, model_name="Facenet", enforce_detection=False)
        similarity = round((1 - df_res.get("distance", 1.0)) * 100, 2)
        face_match = df_res.get("verified", False)
    except Exception:
        face_match = False
        similarity = 0.0
    finally:
        if os.path.exists(temp_id): os.remove(temp_id)
        if os.path.exists(temp_selfie): os.remove(temp_selfie)

    is_approved = face_match and (similarity >= 75.0) and (not vision_res["is_screen"])
    final_status = KYCStatus.APPROVED if is_approved else KYCStatus.REJECTED

    kyc_req = KYCRequest(
        user_id=payload.user_id,
        extracted_id_number=id_number,
        face_match_score=similarity,
        is_live_selfie=not vision_res["is_blurry"],
        status=final_status,
        rejection_reason=None if is_approved else "فشل في المطابقة البيومترية أو كشف التزوير"
    )
    db.add(kyc_req)
    db.flush()

    doc = VerificationDocument(
        kyc_request_id=kyc_req.id,
        doc_type=DocumentType.NATIONAL_ID,
        file_path="uploads/id_card.jpg",
        raw_ocr_data={"text": ocr_res}
    )
    db.add(doc)

    if vision_res["is_screen"] or not face_match:
        fraud = FraudLog(
            kyc_request_id=kyc_req.id,
            risk_level=FraudRiskLevel.CRITICAL if vision_res["is_screen"] else FraudRiskLevel.HIGH,
            fraud_type="SCREEN_RECAPTURE" if vision_res["is_screen"] else "FACE_MISMATCH",
            is_screen_detected=vision_res["is_screen"],
            technical_details={"fft": vision_res["fft_score"], "similarity": similarity}
        )
        db.add(fraud)

    db.commit()

    return {
        "status": "success",
        "kyc_id": str(kyc_req.id),
        "kyc_status": final_status.value,
        "similarity_score": f"{similarity}%",
        "ocr_text": ocr_res
    }
