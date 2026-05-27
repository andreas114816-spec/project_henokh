import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import calendar
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session as flask_session
import base64
import cv2
import numpy as np
from database import SessionLocal, init_db, migrate_db, seed_admin_user
from models.db_models import AppSetting, Attendance, SchoolClass, Student, Teacher, User
from sqlalchemy.orm import selectinload

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "henokh-dev-secret-key")
BASE_DIR = Path(__file__).resolve().parent
FACE_MODEL_PATH = BASE_DIR / "model" / "best.pt"
SPOOF_MODEL_PATH = BASE_DIR / "model" / "mini_cnn_real_spoof.keras"
SPOOF_LABELS = ("real", "spoof")
ANTI_SPOOF_SETTING_KEY = "anti_spoof_enabled"
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.55"))
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Jakarta"))

face_model = None
spoof_model = None


class ModelUnavailableError(RuntimeError):
    pass


def parse_time_field(value):
    value = (value or "").strip()

    if not value:
        return None

    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def parse_optional_int(value):
    value = (value or "").strip()

    if not value:
        return None

    return int(value) if value.isdigit() else None


def parse_date_field(value):
    value = (value or "").strip()

    if not value:
        return None

    return date.fromisoformat(value)


def parse_datetime_local_field(value):
    value = (value or "").strip()

    if not value:
        return current_app_datetime()

    return datetime.fromisoformat(value)


def current_app_datetime():
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not flask_session.get("user_id"):
            return redirect(url_for("index"))

        return view(*args, **kwargs)

    return wrapped_view


def string_to_bool(value, default=True):
    if value is None:
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def is_anti_spoof_enabled():
    session = SessionLocal()

    try:
        setting = session.query(AppSetting).filter_by(key=ANTI_SPOOF_SETTING_KEY).one_or_none()
        return string_to_bool(setting.value if setting else None, default=True)
    except Exception:
        return True
    finally:
        SessionLocal.remove()


def set_anti_spoof_enabled(enabled):
    session = SessionLocal()

    try:
        setting = session.query(AppSetting).filter_by(key=ANTI_SPOOF_SETTING_KEY).one_or_none()

        if setting is None:
            setting = AppSetting(key=ANTI_SPOOF_SETTING_KEY, value="true")
            session.add(setting)

        setting.value = "true" if enabled else "false"
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()


def build_presence_dashboard_context(session):
    today = current_app_datetime().date()
    selected_class_id = request.args.get("class_id", type=int)
    selected_date = parse_date_field(request.args.get("date"))
    month_value = request.args.get("month", "")

    try:
        month_start = datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
    except ValueError:
        month_start = today.replace(day=1)

    presence_classes = (
        session.query(SchoolClass)
        .options(selectinload(SchoolClass.students))
        .order_by(SchoolClass.name.asc())
        .all()
    )

    if selected_class_id is None and presence_classes:
        selected_class_id = presence_classes[0].id

    selected_class = None

    if selected_class_id:
        selected_class = next(
            (school_class for school_class in presence_classes if school_class.id == selected_class_id),
            None
        )

    if selected_date is None:
        selected_date = today if today.year == month_start.year and today.month == month_start.month else None

    month_end_day = calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = month_start.replace(day=month_end_day)
    attendance_rows = []

    if selected_class:
        attendance_rows = (
            session.query(Attendance)
            .filter(
                Attendance.class_id == selected_class.id,
                Attendance.attendance_date >= month_start,
                Attendance.attendance_date <= month_end
            )
            .all()
        )

    summaries = {}

    for attendance in attendance_rows:
        summary = summaries.setdefault(attendance.attendance_date, {
            "presence": 0,
            "late": 0,
            "absen": 0
        })

        if attendance.status in summary:
            summary[attendance.status] += 1

    calendar_weeks = []
    month_calendar = calendar.Calendar(firstweekday=0)

    for week in month_calendar.monthdatescalendar(month_start.year, month_start.month):
        calendar_weeks.append([
            {
                "date": day,
                "in_month": day.month == month_start.month,
                "summary": summaries.get(day, {"presence": 0, "late": 0, "absen": 0})
            }
            for day in week
        ])

    detail_rows = []

    if selected_class and selected_date:
        attendance_by_student_id = {
            attendance.student_id: attendance
            for attendance in session.query(Attendance)
            .filter_by(class_id=selected_class.id, attendance_date=selected_date)
            .all()
        }

        for student in selected_class.students:
            detail_rows.append({
                "student": student,
                "attendance": attendance_by_student_id.get(student.id)
            })

    previous_month = (month_start.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (
        month_start.replace(day=month_end_day) + timedelta(days=1)
    ).replace(day=1)

    return {
        "classes": presence_classes,
        "selected_class": selected_class,
        "selected_class_id": selected_class_id,
        "month": month_start,
        "previous_month": previous_month,
        "next_month": next_month,
        "calendar_weeks": calendar_weeks,
        "selected_date": selected_date,
        "detail_rows": detail_rows,
    }


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
            flask_session.clear()
            flask_session["user_id"] = user.id
            flask_session["username"] = user.username
            return redirect(url_for("dashboard"))
    finally:
        SessionLocal.remove()

    return render_template("index.html", error="Invalid username or password"), 401


@app.route("/logout", methods=["POST"])
def logout():
    flask_session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    active_section = request.args.get("section", "overview")
    allowed_sections = {"overview", "students", "teachers", "classes", "users", "presence", "settings"}

    if active_section not in allowed_sections:
        active_section = "overview"

    session = SessionLocal()

    try:
        students = session.query(Student).order_by(Student.created_at.desc()).all()
        teachers = session.query(Teacher).order_by(Teacher.created_at.desc()).all()
        classes = (
            session.query(SchoolClass)
            .options(
                selectinload(SchoolClass.teacher),
                selectinload(SchoolClass.students)
            )
            .order_by(SchoolClass.created_at.desc())
            .all()
        )
        users = session.query(User).order_by(User.created_at.desc()).all()
        presence_context = (
            build_presence_dashboard_context(session)
            if active_section == "presence"
            else None
        )

        return render_template(
            "dashboard.html",
            students=students,
            teachers=teachers,
            classes=classes,
            users=users,
            active_section=active_section,
            current_user_id=flask_session.get("user_id"),
            username=flask_session.get("username"),
            anti_spoof_enabled=is_anti_spoof_enabled(),
            presence_context=presence_context
        )
    finally:
        SessionLocal.remove()


@app.route("/attendance/update", methods=["POST"])
@login_required
def update_attendance():
    class_id = parse_optional_int(request.form.get("class_id"))
    student_id = parse_optional_int(request.form.get("student_id"))
    attendance_date = parse_date_field(request.form.get("attendance_date"))
    status = (request.form.get("status") or "").strip()
    presence_at = parse_datetime_local_field(request.form.get("presence_at"))
    month = request.form.get("month") or (attendance_date.strftime("%Y-%m") if attendance_date else "")

    if not class_id or not student_id or not attendance_date or status not in {"presence", "late", "absen"}:
        return redirect(url_for("dashboard", section="presence", class_id=class_id or "", month=month))

    session = SessionLocal()

    try:
        attendance = (
            session.query(Attendance)
            .filter_by(
                class_id=class_id,
                student_id=student_id,
                attendance_date=attendance_date
            )
            .one_or_none()
        )

        if attendance is None:
            attendance = Attendance(
                class_id=class_id,
                student_id=student_id,
                attendance_date=attendance_date,
                status=status,
                presence_at=presence_at
            )
            session.add(attendance)
        else:
            attendance.status = status
            attendance.presence_at = presence_at

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for(
        "dashboard",
        section="presence",
        class_id=class_id,
        month=month,
        date=attendance_date.isoformat()
    ))


@app.route("/settings/anti-spoof", methods=["POST"])
@login_required
def update_anti_spoof_setting():
    set_anti_spoof_enabled(request.form.get("anti_spoof_enabled") == "on")
    return redirect(url_for("dashboard", section="settings"))


@app.route("/teachers", methods=["POST"])
@login_required
def create_teacher():
    name = request.form.get("name", "").strip()
    nip = request.form.get("nip", "").strip()
    subject = request.form.get("subject", "").strip() or None

    if not name or not nip:
        return redirect(url_for("dashboard", section="teachers", error="teacher"))

    session = SessionLocal()

    try:
        teacher = session.query(Teacher).filter_by(nip=nip).one_or_none()

        if teacher is None:
            teacher = Teacher(name=name, nip=nip, subject=subject)
            session.add(teacher)
        else:
            teacher.name = name
            teacher.subject = subject

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="teachers"))


@app.route("/users", methods=["POST"])
@login_required
def create_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return redirect(url_for("dashboard", section="users", error="user"))

    session = SessionLocal()

    try:
        user = session.query(User).filter_by(username=username).one_or_none()

        if user is None:
            user = User(username=username)
            session.add(user)

        user.set_password(password)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="users"))


@app.route("/classes", methods=["POST"])
@login_required
def create_class():
    name = request.form.get("name", "").strip()
    class_code = request.form.get("class_code", "").strip()
    teacher_id = parse_optional_int(request.form.get("teacher_id"))
    start_time = parse_time_field(request.form.get("start_time"))
    end_time = parse_time_field(request.form.get("end_time"))
    start_presence = parse_time_field(request.form.get("start_presence"))
    end_presence = parse_time_field(request.form.get("end_presence"))
    student_ids = request.form.getlist("student_ids")

    if not name or not class_code:
        return redirect(url_for("new_class", error="class"))

    session = SessionLocal()

    try:
        school_class = session.query(SchoolClass).filter_by(class_code=class_code).one_or_none()

        if school_class is None:
            school_class = SchoolClass(name=name, class_code=class_code)
            session.add(school_class)
        else:
            school_class.name = name

        school_class.start_time = start_time
        school_class.end_time = end_time
        school_class.start_presence = start_presence
        school_class.end_presence = end_presence
        school_class.teacher_id = teacher_id
        school_class.teacher = session.get(Teacher, teacher_id) if teacher_id else None

        selected_student_ids = [
            int(student_id)
            for student_id in student_ids
            if student_id.isdigit()
        ]
        school_class.students = (
            session.query(Student)
            .filter(Student.id.in_(selected_student_ids))
            .all()
            if selected_student_ids
            else []
        )

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="classes"))


@app.route("/classes/<int:class_id>/delete", methods=["POST"])
@login_required
def delete_class(class_id):
    session = SessionLocal()

    try:
        school_class = session.get(SchoolClass, class_id)

        if school_class:
            session.delete(school_class)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="classes"))


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    session = SessionLocal()

    try:
        student = session.get(Student, student_id)

        if student:
            session.delete(student)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="students"))


@app.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@login_required
def delete_teacher(teacher_id):
    session = SessionLocal()

    try:
        teacher = session.get(Teacher, teacher_id)

        if teacher:
            session.delete(teacher)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="teachers"))


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    if user_id == flask_session.get("user_id"):
        return redirect(url_for("dashboard", section="users"))

    session = SessionLocal()

    try:
        user = session.get(User, user_id)

        if user:
            session.delete(user)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="users"))


@app.route("/students/new")
@login_required
def new_student():
    return render_template("student_form.html", active_section="students")


@app.route("/teachers/new")
@login_required
def new_teacher():
    return render_template("teacher_form.html", active_section="teachers")


@app.route("/users/new")
@login_required
def new_user():
    return render_template("user_form.html", active_section="users")


@app.route("/classes/new")
@login_required
def new_class():
    session = SessionLocal()

    try:
        students = session.query(Student).order_by(Student.name.asc()).all()
        teachers = session.query(Teacher).order_by(Teacher.name.asc()).all()

        return render_template(
            "class_form.html",
            active_section="classes",
            students=students,
            teachers=teachers
        )
    finally:
        SessionLocal.remove()


@app.route("/presence")
def presence():
    auto_start = request.args.get("start") == "1"
    selected_class_id = request.args.get("class_id", type=int)
    session = SessionLocal()

    try:
        classes = session.query(SchoolClass).order_by(SchoolClass.name.asc()).all()
    except Exception:
        classes = []
    finally:
        SessionLocal.remove()

    return render_template(
        "presence.html",
        auto_start=auto_start,
        classes=classes,
        selected_class_id=selected_class_id
    )


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


def get_model_label(model, class_id):
    names = getattr(model, "names", {})

    if isinstance(names, dict):
        return names.get(class_id, "face")

    if isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
        return names[class_id]

    return "face"


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


def is_time_between(current_time, start_time, end_time):
    if not start_time or not end_time:
        return True

    if start_time <= end_time:
        return start_time <= current_time <= end_time

    return current_time >= start_time or current_time <= end_time


def get_attendance_status(school_class, checked_at):
    current_time = checked_at.time()

    if not is_time_between(current_time, school_class.start_presence, school_class.end_presence):
        return None, "Outside presence time"

    if school_class.start_time and current_time <= school_class.start_time:
        return "presence", "On time"

    if school_class.end_time and current_time <= school_class.end_time:
        return "late", "Late"

    if school_class.end_time and current_time > school_class.end_time:
        return "absen", "After class ended"

    return "presence", "Presence recorded"


def save_attendance_record(session, school_class, student, status, presence_at):
    attendance_date = presence_at.date()
    attendance = (
        session.query(Attendance)
        .filter_by(
            class_id=school_class.id,
            student_id=student.id,
            attendance_date=attendance_date
        )
        .one_or_none()
    )

    if attendance is None:
        attendance = Attendance(
            class_id=school_class.id,
            student_id=student.id,
            attendance_date=attendance_date,
            status=status,
            presence_at=presence_at
        )
        session.add(attendance)
        action = "created"
    else:
        action = "existing"

        if attendance.status == "absen" and status in {"presence", "late"}:
            attendance.status = status
            attendance.presence_at = presence_at
            action = "updated"

    return attendance, action


def mark_absent_students_after_class(session, school_class, checked_at):
    if not school_class.end_time or checked_at.time() <= school_class.end_time:
        return 0

    attendance_date = checked_at.date()
    created_count = 0

    for student in school_class.students:
        attendance = (
            session.query(Attendance)
            .filter_by(
                class_id=school_class.id,
                student_id=student.id,
                attendance_date=attendance_date
            )
            .one_or_none()
        )

        if attendance is None:
            session.add(Attendance(
                class_id=school_class.id,
                student_id=student.id,
                attendance_date=attendance_date,
                status="absen",
                presence_at=checked_at
            ))
            created_count += 1

    return created_count


def serialize_attendance(attendance, action=None, message=None):
    if attendance is None:
        return {
            "recorded": False,
            "message": message or "Attendance not recorded"
        }

    return {
        "recorded": True,
        "action": action,
        "status": attendance.status,
        "presenceAt": attendance.presence_at.isoformat(),
        "date": attendance.attendance_date.isoformat(),
        "message": message or "Attendance recorded"
    }


def identify_detected_faces(frame, detections, class_id=None, record_attendance=False):
    if not detections:
        return detections

    session = SessionLocal()

    try:
        school_class = None

        if class_id:
            school_class = session.get(SchoolClass, class_id)
            students = school_class.students if school_class else []
        else:
            students = session.query(Student).all()

        known_students = [
            (student, np.asarray(student.face_embeddings, dtype="float32"))
            for student in students
            if student.face_embeddings
        ]

        if not known_students:
            return detections

        from models.mobilefacenet import build_face_embedding

        for detection in detections:
            face = crop_detected_face(frame, detection)

            if face is None:
                continue

            try:
                embedding = np.asarray(build_face_embedding(face), dtype="float32")
            except Exception as error:
                detection["identity"] = {
                    "matched": False,
                    "error": str(error)
                }
                continue

            best_student = None
            best_similarity = -1.0

            for student, known_embedding in known_students:
                if known_embedding.shape != embedding.shape:
                    continue

                similarity = float(np.dot(embedding, known_embedding))

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_student = student

            if best_student and best_similarity >= FACE_MATCH_THRESHOLD:
                detection["identity"] = {
                    "matched": True,
                    "studentId": best_student.id,
                    "name": best_student.name,
                    "nim": best_student.nim,
                    "similarity": round(best_similarity, 4)
                }

                if school_class and record_attendance:
                    checked_at = current_app_datetime()
                    status, message = get_attendance_status(school_class, checked_at)

                    if status:
                        attendance, action = save_attendance_record(
                            session,
                            school_class,
                            best_student,
                            status,
                            checked_at
                        )
                        session.commit()
                        detection["attendance"] = serialize_attendance(attendance, action=action, message=message)
                    else:
                        detection["attendance"] = serialize_attendance(None, message=message)
            else:
                detection["identity"] = {
                    "matched": False,
                    "similarity": round(best_similarity, 4)
                }

        if school_class and record_attendance:
            checked_at = current_app_datetime()
            if mark_absent_students_after_class(session, school_class, checked_at):
                session.commit()

        return detections
    except Exception:
        return detections
    finally:
        SessionLocal.remove()


def disabled_liveness_result():
    return {
        "label": "disabled",
        "classId": None,
        "confidence": 1,
        "scores": {"real": 1, "spoof": 0},
        "enabled": False
    }


def detect_faces(frame, anti_spoof_enabled=None):
    if anti_spoof_enabled is None:
        anti_spoof_enabled = is_anti_spoof_enabled()

    model = get_face_model()
    results = model.predict(frame, conf=0.35, verbose=False)
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


@app.route("/students", methods=["POST"])
@login_required
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

    anti_spoof_enabled = is_anti_spoof_enabled()

    try:
        detections = detect_faces(frame, anti_spoof_enabled=anti_spoof_enabled)
    except ModelUnavailableError as error:
        return jsonify({"success": False, "message": str(error)}), 503

    if len(detections) != 1:
        return jsonify({
            "success": False,
            "message": "Capture exactly one face before saving"
        }), 400

    detection = detections[0]
    real_score = (detection.get("liveness") or {}).get("scores", {}).get("real", 0)

    if anti_spoof_enabled and real_score < 0.5:
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
        face_embedding = None
        embedding_warning = str(error)
    else:
        embedding_warning = None

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

        if face_embedding is not None:
            student.set_face_embedding(face_embedding)

        session.commit()

        message = f"Student {action}"

        if embedding_warning:
            message += ". MobileFaceNet model missing, saved without face embedding"

        return jsonify({
            "success": True,
            "message": message,
            "warning": embedding_warning,
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
    class_id = data.get("classId")

    try:
        class_id = int(class_id) if class_id else None
    except (TypeError, ValueError):
        class_id = None

    try:
        anti_spoof_enabled = is_anti_spoof_enabled()
        detections = detect_faces(frame, anti_spoof_enabled=anti_spoof_enabled)
        detections = identify_detected_faces(
            frame,
            detections,
            class_id=class_id,
            record_attendance=class_id is not None
        )
    except ModelUnavailableError as error:
        return jsonify({"success": False, "message": str(error)}), 503

    print(f"Received frame: {width}x{height}, detections: {len(detections)}")

    return jsonify({
        "success": True,
        "message": "Frame processed",
        "width": width,
        "height": height,
        "antiSpoofEnabled": anti_spoof_enabled,
        "classId": class_id,
        "detections": detections
    })


if __name__ == "__main__":
    app.run(debug=True)
