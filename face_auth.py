"""
F.R.I.D.A.Y. Face Recognition Module
Uses OpenCV LBPH - no heavy dependencies, works out of the box.
Needs only: pip install opencv-python
"""

import os
import json
import base64
import hashlib
import time
import numpy as np
from datetime import datetime

FACES_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "friday_faces")
CONFIG     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "friday_faces_config.json")
PIN_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "friday_pin.json")
MODEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "friday_face_model.yml")

CV2_AVAILABLE = False
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    pass

# OpenCV face detector XML - built into opencv
CASCADE_PATH = None
if CV2_AVAILABLE:
    import cv2
    CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


# ── CONFIG ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG):
        try:
            return json.load(open(CONFIG, "r"))
        except Exception:
            pass
    return {"enrolled": False, "pin_enabled": False}


def save_config(cfg: dict):
    with open(CONFIG, "w") as f:
        json.dump(cfg, f)


# ── PIN ────────────────────────────────────────────────────────────────────────

def set_pin(pin: str) -> dict:
    try:
        pin = pin.strip()
        if len(pin) < 4:
            return {"success": False, "message": "PIN must be at least 4 digits."}
        h = hashlib.sha256(pin.encode()).hexdigest()
        with open(PIN_FILE, "w") as f:
            json.dump({"hash": h}, f)
        cfg = load_config()
        cfg["pin_enabled"] = True
        save_config(cfg)
        print(f"[FaceAuth] PIN set successfully.")
        return {"success": True, "message": "PIN saved."}
    except Exception as e:
        return {"success": False, "message": f"PIN error: {e}"}


def verify_pin(pin: str) -> bool:
    try:
        if not os.path.exists(PIN_FILE):
            print("[FaceAuth] No PIN file found.")
            return False
        with open(PIN_FILE, "r") as f:
            data = json.load(f)
        stored = data.get("hash", "")
        entered = hashlib.sha256(pin.strip().encode()).hexdigest()
        result = (stored == entered)
        print(f"[FaceAuth] PIN verify: {'OK' if result else 'FAILED'}")
        return result
    except Exception as e:
        print(f"[FaceAuth] PIN verify error: {e}")
        return False


# ── ENROLL ─────────────────────────────────────────────────────────────────────

def enroll_face(frames: int = 30) -> dict:
    if not CV2_AVAILABLE:
        return {"success": False, "message": "opencv-python not installed. Run: pip install opencv-python"}

    os.makedirs(FACES_DIR, exist_ok=True)

    detector = cv2.CascadeClassifier(CASCADE_PATH)
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        return {"success": False, "message": "Could not open webcam. Make sure no other app is using it."}

    faces_collected = []
    saved = 0
    attempts = 0

    print(f"[FaceAuth] Enrolling face — collecting {frames} samples...")

    while saved < frames and attempts < frames * 8:
        attempts += 1
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detected = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))

        for (x, y, w, h) in detected:
            face_roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))
            faces_collected.append(face_roi)
            saved += 1
            if saved >= frames:
                break

        time.sleep(0.1)

    cap.release()

    if saved < 10:
        return {
            "success": False,
            "message": f"Only captured {saved} face samples. Make sure your face is well-lit and visible to the camera."
        }

    # Train LBPH recognizer
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    labels = [0] * len(faces_collected)  # label 0 = you
    recognizer.train(faces_collected, np.array(labels))
    recognizer.write(MODEL_FILE)

    cfg = load_config()
    cfg["enrolled"]    = True
    cfg["enrolled_at"] = datetime.now().isoformat()
    cfg["samples"]     = saved
    save_config(cfg)

    print(f"[FaceAuth] Enrolled with {saved} samples. Model saved.")
    return {"success": True, "message": f"Face enrolled with {saved} samples. You're all set, Boss."}


def delete_enrollment():
    import shutil
    if os.path.exists(FACES_DIR):
        shutil.rmtree(FACES_DIR)
    if os.path.exists(MODEL_FILE):
        os.remove(MODEL_FILE)
    cfg = load_config()
    cfg["enrolled"] = False
    save_config(cfg)


# ── VERIFY ─────────────────────────────────────────────────────────────────────

def verify_face_from_frame(frame_b64: str) -> dict:
    if not CV2_AVAILABLE:
        return {"verified": False, "confidence": 0, "message": "opencv-python not installed."}

    cfg = load_config()
    if not cfg.get("enrolled") or not os.path.exists(MODEL_FILE):
        return {"verified": False, "confidence": 0, "message": "No face enrolled. Click ENROLL FACE first."}

    try:
        # Decode base64 frame
        img_data = base64.b64decode(frame_b64)
        nparr    = np.frombuffer(img_data, np.uint8)
        frame    = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return {"verified": False, "confidence": 0, "message": "Could not decode image."}

        gray     = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detector = cv2.CascadeClassifier(CASCADE_PATH)
        detected = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))

        if len(detected) == 0:
            return {"verified": False, "confidence": 0, "message": "No face detected in frame."}

        # Load model and predict
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.read(MODEL_FILE)

        best_confidence = None
        for (x, y, w, h) in detected:
            face_roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))
            label, confidence = recognizer.predict(face_roi)
            # LBPH: lower confidence = better match (0 = perfect)
            if best_confidence is None or confidence < best_confidence:
                best_confidence = confidence

        # Convert LBPH distance to a 0-100% score (threshold ~80)
        threshold    = 80
        match_pct    = round(max(0, (1 - best_confidence / 150)) * 100, 1)
        verified     = best_confidence < threshold

        print(f"[FaceAuth] Confidence: {best_confidence:.1f} — {'MATCH' if verified else 'NO MATCH'}")

        return {
            "verified":   verified,
            "confidence": match_pct,
            "message":    "Access granted." if verified else f"Face not recognised ({match_pct}% match).",
        }

    except Exception as e:
        print(f"[FaceAuth] Verify error: {e}")
        return {"verified": False, "confidence": 0, "message": f"Error: {e}"}


def is_enrolled() -> bool:
    cfg = load_config()
    return cfg.get("enrolled", False) and os.path.exists(MODEL_FILE)


def is_available() -> bool:
    return CV2_AVAILABLE
