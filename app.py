import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

from pathlib import Path

from flask import Flask, render_template, request, jsonify, redirect, url_for
import base64
import cv2
import numpy as np
from database import SessionLocal, init_db, migrate_db, seed_admin_user
from models.db_models import Student, User

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
FACE_MODEL_PATH = BASE_DIR / "model" / "best.pt"
SPOOF_MODEL_PATH = BASE_DIR / "model" / "mini_cnn_real_spoof.keras"
SPOOF_LABELS = ("real", "spoof")

face_model = None
spoof_model = None


class ModelUnavailableError(RuntimeError):
    pass


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


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Initialized database tables.")


@app.cli.command("migrate-db")
def migrate_db_command():
    migrate_db()
    print("Database migration step completed.")


@app.cli.command("seed-admin")
def seed_admin_command():
    action = seed_admin_user(username="admin", password="admin123")
    print(f"Admin user {action}: admin")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    session = SessionLocal()

    try:
        user = session.query(User).filter_by(username=username).one_or_none()

        if user and user.check_password(password):
            return redirect(url_for("new_student"))
    finally:
        SessionLocal.remove()

    return render_template("index.html", error="Invalid username or password"), 401


@app.route("/students/new")
def new_student():
    return render_template("student_form.html")


@app.route("/presence")
def presence():
    auto_start = request.args.get("start") == "1"
    return render_template("presence.html", auto_start=auto_start)


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
    scores = get_spoof_model().predict(np.expand_dims(face, axis=0), verbose=0)[0]
    class_id = int(np.argmax(scores))

    return {
        "label": SPOOF_LABELS[class_id],
        "classId": class_id,
        "confidence": round(float(scores[class_id]), 4),
        "scores": {
            label: round(float(score), 4)
            for label, score in zip(SPOOF_LABELS, scores)
        }
    }


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


def detect_faces(frame):
    model = get_face_model()
    results = model.predict(frame, conf=0.35, verbose=False)
    detections = []

    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            confidence = float(box.conf[0])
            class_id = int(box.cls[0])

            try:
                liveness = classify_real_spoof(frame, x1, y1, x2, y2)
            except ModelUnavailableError as error:
                liveness = {
                    "label": "unverified",
                    "classId": None,
                    "confidence": 0,
                    "scores": {"real": 0, "spoof": 1},
                    "error": str(error)
                }

            detections.append({
                "x": round(x1, 2),
                "y": round(y1, 2),
                "width": round(x2 - x1, 2),
                "height": round(y2 - y1, 2),
                "confidence": round(confidence, 4),
                "classId": class_id,
                "label": model.names.get(class_id, "face"),
                "liveness": liveness
            })

    return detections


@app.route("/students", methods=["POST"])
def create_student():
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "message": "No student data received"}), 400

    name = data.get("name", "").strip()
    nim = data.get("nim", "").strip()
    image_data = data.get("image", "")

    if not name or not nim or not image_data:
        return jsonify({
            "success": False,
            "message": "Name, NIM, and face image are required"
        }), 400

    frame = decode_image_data(image_data)

    if frame is None:
        return jsonify({"success": False, "message": "Invalid face image"}), 400

    try:
        detections = detect_faces(frame)
    except ModelUnavailableError as error:
        return jsonify({"success": False, "message": str(error)}), 503

    if len(detections) != 1:
        return jsonify({
            "success": False,
            "message": "Capture exactly one face before saving"
        }), 400

    detection = detections[0]
    real_score = (detection.get("liveness") or {}).get("scores", {}).get("real", 0)

    if real_score < 0.5:
        return jsonify({
            "success": False,
            "message": "Face must pass real-person check before saving"
        }), 400

    face = crop_detected_face(frame, detection)

    if face is None:
        return jsonify({"success": False, "message": "Unable to crop detected face"}), 400

    try:
        from models.mobilefacenet import build_face_embedding

        face_embedding = build_face_embedding(face)
    except FileNotFoundError as error:
        return jsonify({"success": False, "message": str(error)}), 503

    session = SessionLocal()

    try:
        student = session.query(Student).filter_by(nim=nim).one_or_none()

        if student is None:
            student = Student(name=name, nim=nim)
            session.add(student)
            action = "created"
        else:
            student.name = name
            action = "updated"

        student.set_face_embedding(face_embedding)
        session.commit()

        return jsonify({
            "success": True,
            "message": f"Student {action}",
            "student": {
                "id": student.id,
                "name": student.name,
                "nim": student.nim,
                "embeddingDimensions": len(student.face_embeddings or [])
            }
        })
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()


@app.route("/upload-frame", methods=["POST"])
def upload_frame():
    data = request.get_json()

    if not data or "image" not in data:
        return jsonify({
            "success": False,
            "message": "No image received"
        }), 400

    frame = decode_image_data(data["image"])

    if frame is None:
        return jsonify({
            "success": False,
            "message": "Invalid image"
        }), 400

    height, width, channels = frame.shape
    try:
        detections = detect_faces(frame)
    except ModelUnavailableError as error:
        return jsonify({"success": False, "message": str(error)}), 503

    print(f"Received frame: {width}x{height}, detections: {len(detections)}")

    return jsonify({
        "success": True,
        "message": "Frame processed",
        "width": width,
        "height": height,
        "detections": detections
    })


if __name__ == "__main__":
    app.run(debug=True)
