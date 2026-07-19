import base64
import logging
import os
from pathlib import Path
import time

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import cv2
import numpy as np
from flask import Flask, jsonify, request

from models.mobilefacenet import build_face_embedding


app = Flask(__name__)
logging.basicConfig(level=os.getenv("AI_SERVICE_LOG_LEVEL", "INFO"))
app.logger.setLevel(os.getenv("AI_SERVICE_LOG_LEVEL", "INFO"))

BASE_DIR = Path(__file__).resolve().parent
FACE_MODEL_PATH = Path(os.getenv("FACE_MODEL_PATH", BASE_DIR / "model" / "best.pt")).expanduser()
SPOOF_MODEL_PATH = Path(os.getenv("SPOOF_MODEL_PATH", BASE_DIR / "model" / "mini_cnn_real_spoof.keras")).expanduser()
SPOOF_LABELS = ("real", "spoof")
SPOOF_REAL_THRESHOLD = float(os.getenv("SPOOF_REAL_THRESHOLD", "0.3"))

face_model = None
spoof_model = None

try:
    import psutil
except ImportError:
    psutil = None

process = psutil.Process(os.getpid()) if psutil else None


class ModelUnavailableError(RuntimeError):
    pass


def get_resource_snapshot():
    if process is None:
        return None

    with process.oneshot():
        cpu_times = process.cpu_times()
        return {
            "rss_mb": process.memory_info().rss / (1024 * 1024),
            "cpu_seconds": cpu_times.user + cpu_times.system
        }


def log_model_inference(model_name, elapsed_seconds, before_snapshot, after_snapshot):
    if before_snapshot is None or after_snapshot is None:
        app.logger.info(
            "AI model inference | model=%s inference_ms=%.2f ram_mb=unavailable cpu_percent=unavailable",
            model_name,
            elapsed_seconds * 1000
        )
        return

    cpu_delta = after_snapshot["cpu_seconds"] - before_snapshot["cpu_seconds"]
    cpu_percent = (cpu_delta / elapsed_seconds) * 100 if elapsed_seconds > 0 else 0
    ram_delta_mb = after_snapshot["rss_mb"] - before_snapshot["rss_mb"]

    app.logger.info(
        "AI model inference | model=%s inference_ms=%.2f ram_mb=%.2f ram_delta_mb=%+.2f cpu_percent=%.2f",
        model_name,
        elapsed_seconds * 1000,
        after_snapshot["rss_mb"],
        ram_delta_mb,
        cpu_percent
    )


def run_measured_model(model_name, callback):
    before_snapshot = get_resource_snapshot()
    started_at = time.perf_counter()

    try:
        return callback()
    finally:
        elapsed_seconds = time.perf_counter() - started_at
        after_snapshot = get_resource_snapshot()
        log_model_inference(model_name, elapsed_seconds, before_snapshot, after_snapshot)


def get_face_model():
    global face_model

    if face_model is None:
        try:
            from ultralytics import YOLO

            face_model = YOLO(str(FACE_MODEL_PATH))
        except Exception as error:
            raise ModelUnavailableError(f"Face detection model unavailable: {error}") from error

    return face_model


def get_spoof_model():
    global spoof_model

    if spoof_model is None:
        try:
            from models.mini_cnn import build_mini_cnn

            spoof_model = build_mini_cnn()
            spoof_model.load_weights(str(SPOOF_MODEL_PATH))
        except Exception as error:
            raise ModelUnavailableError(f"Spoof detection model unavailable: {error}") from error

    return spoof_model


def decode_image_data(image_data):
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    image_bytes = base64.b64decode(image_data)
    np_arr = np.frombuffer(image_bytes, np.uint8)
    return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)


def crop_detected_face(frame, detection):
    frame_height, frame_width = frame.shape[:2]
    left = max(0, int(detection["x"]))
    top = max(0, int(detection["y"]))
    right = min(frame_width, int(detection["x"] + detection["width"]))
    bottom = min(frame_height, int(detection["y"] + detection["height"]))

    if right <= left or bottom <= top:
        return None

    return frame[top:bottom, left:right]


def classify_real_spoof(frame, x1, y1, x2, y2):
    frame_height, frame_width = frame.shape[:2]
    left = max(0, int(x1))
    top = max(0, int(y1))
    right = min(frame_width, int(x2))
    bottom = min(frame_height, int(y2))

    if right <= left or bottom <= top:
        return None

    face = frame[top:bottom, left:right]
    face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
    face = cv2.resize(face, (112, 112), interpolation=cv2.INTER_AREA)
    face = face.astype("float32") / 255.0
    scores = run_measured_model(
        "MiniCNN anti-spoof",
        lambda: get_spoof_model().predict(np.expand_dims(face, axis=0), verbose=0)[0]
    )
    real_score = float(scores[0])
    class_id = 0 if real_score >= SPOOF_REAL_THRESHOLD else 1

    return {
        "label": SPOOF_LABELS[class_id],
        "classId": class_id,
        "confidence": round(real_score, 4),
        "scores": {
            label: round(float(score), 4)
            for label, score in zip(SPOOF_LABELS, scores)
        },
        "threshold": SPOOF_REAL_THRESHOLD
    }


def disabled_liveness_result():
    return {
        "label": "disabled",
        "classId": None,
        "confidence": 1,
        "scores": {"real": 1, "spoof": 0},
        "enabled": False
    }


def get_model_label(model, class_id):
    names = getattr(model, "names", {})

    if isinstance(names, dict):
        return names.get(class_id, "face")

    if isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
        return names[class_id]

    return "face"


def detect_faces(frame, anti_spoof_enabled=True):
    model = get_face_model()
    results = run_measured_model(
        "YOLO face detection",
        lambda: model.predict(frame, conf=0.35, verbose=False)
    )
    detections = []

    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            confidence = float(box.conf[0])
            class_id = int(box.cls[0])

            if anti_spoof_enabled:
                try:
                    liveness = classify_real_spoof(frame, x1, y1, x2, y2)
                    liveness["enabled"] = True
                except Exception as error:
                    liveness = {
                        "label": "unverified",
                        "classId": None,
                        "confidence": 0,
                        "scores": {"real": 0, "spoof": 1},
                        "enabled": True,
                        "error": str(error)
                    }
            else:
                liveness = disabled_liveness_result()

            detections.append({
                "bbox": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "x": round(x1, 2),
                "y": round(y1, 2),
                "width": round(x2 - x1, 2),
                "height": round(y2 - y1, 2),
                "confidence": round(confidence, 4),
                "classId": class_id,
                "label": get_model_label(model, class_id),
                "liveness": liveness
            })

    return detections


def add_embeddings(frame, detections):
    for detection in detections:
        face = crop_detected_face(frame, detection)

        if face is None:
            detection["embeddingError"] = "Unable to crop detected face"
            continue

        try:
            detection["embedding"] = run_measured_model(
                "MobileFaceNet embedding",
                lambda: build_face_embedding(face)
            )
        except FileNotFoundError as error:
            detection["embeddingError"] = str(error)
        except Exception as error:
            detection["embeddingError"] = f"Unable to build face embedding: {error}"

    return detections


@app.get("/health")
def health():
    return jsonify({"success": True, "service": "henokh-ai"})


@app.post("/analyze-frame")
def analyze_frame():
    data = request.get_json(silent=True) or {}
    image_data = data.get("image", "")

    if not image_data:
        return jsonify({"success": False, "message": "No image received"}), 400

    frame = decode_image_data(image_data)

    if frame is None:
        return jsonify({"success": False, "message": "Invalid image"}), 400

    anti_spoof_enabled = bool(data.get("antiSpoofEnabled", True))
    include_embeddings = bool(data.get("includeEmbeddings", False))
    height, width = frame.shape[:2]

    try:
        detections = detect_faces(frame, anti_spoof_enabled=anti_spoof_enabled)

        if include_embeddings:
            detections = add_embeddings(frame, detections)
    except ModelUnavailableError as error:
        return jsonify({"success": False, "message": str(error)}), 503

    return jsonify({
        "success": True,
        "message": "Frame processed",
        "width": width,
        "height": height,
        "antiSpoofEnabled": anti_spoof_enabled,
        "detections": detections
    })


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("AI_SERVICE_PORT", "8001")))
