import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import calendar
import csv
import io
import json
import math
import re
import threading
import uuid
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session as flask_session, flash, send_file
import base64
import cv2
import numpy as np
from ai_client import AIServiceError, analyze_frame
from database import Base, SessionLocal, engine, init_db, migrate_db, seed_admin_user
from models.db_models import AppSetting, Attendance, SchoolClass, Student, Teacher, User, class_students
from sqlalchemy import Date as SQLDate, DateTime as SQLDateTime, MetaData, Table, Time as SQLTime, inspect, or_, select, text
from sqlalchemy.orm import selectinload

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "henokh-dev-secret-key")
BASE_DIR = Path(__file__).resolve().parent
SPOOF_REAL_THRESHOLD = 0.5
ANTI_SPOOF_SETTING_KEY = "anti_spoof_enabled"
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.55"))
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Jakarta"))

PER_PAGE_OPTIONS = (10, 25, 50, 100)
BULK_STUDENT_ROOT = "data"
BULK_STUDENT_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_BULK_STUDENT_ZIP_BYTES = 100 * 1024 * 1024
MAX_BULK_STUDENT_PHOTO_BYTES = 15 * 1024 * 1024
BULK_STUDENT_FAILURE_LOG_DIR = BASE_DIR / "logs"
DEBUG_MODEL_ZIP_BYTES = 100 * 1024 * 1024
DEBUG_MODEL_IMAGE_BYTES = 15 * 1024 * 1024
DEBUG_MODEL_REPORT_DIR = BASE_DIR / "logs"
DEBUG_MODEL_JOBS = {}
DEBUG_MODEL_JOBS_LOCK = threading.Lock()
DATABASE_BACKUP_FORMAT = "henokh-db-backup"
DATABASE_BACKUP_VERSION = 1
MAX_DATABASE_BACKUP_BYTES = 200 * 1024 * 1024


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


def is_digits_only(value):
    return bool(value) and value.isdigit()


def format_person_name(value):
    words = re.sub(r"\s+", " ", (value or "").strip()).split(" ")
    return " ".join(word[:1].upper() + word[1:].lower() for word in words if word)


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


def get_pagination_params(default_per_page=10):
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=default_per_page, type=int)

    if page < 1:
        page = 1

    if per_page not in PER_PAGE_OPTIONS:
        per_page = default_per_page

    return page, per_page


def get_search_query():
    return (request.args.get("q") or "").strip()


def paginate_query(query, page, per_page, search_query=""):
    total = query.enable_eagerloads(False).count()
    total_pages = max(1, math.ceil(total / per_page)) if total else 1
    page = min(max(page, 1), total_pages)
    items = query.limit(per_page).offset((page - 1) * per_page).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
        "per_page_options": PER_PAGE_OPTIONS,
        "q": search_query,
    }


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


def build_archived_cleanup_counts(session):
    return {
        "students": session.query(Student).filter(Student.deleted_at.is_not(None)).count(),
        "teachers": session.query(Teacher).filter(Teacher.deleted_at.is_not(None)).count(),
        "classes": session.query(SchoolClass).filter(SchoolClass.deleted_at.is_not(None)).count(),
    }


def build_archived_restore_data(session):
    return {
        "students": (
            session.query(Student)
            .filter(Student.deleted_at.is_not(None))
            .order_by(Student.deleted_at.desc(), Student.name.asc())
            .all()
        ),
        "teachers": (
            session.query(Teacher)
            .filter(Teacher.deleted_at.is_not(None))
            .order_by(Teacher.deleted_at.desc(), Teacher.name.asc())
            .all()
        ),
        "classes": (
            session.query(SchoolClass)
            .filter(SchoolClass.deleted_at.is_not(None))
            .order_by(SchoolClass.deleted_at.desc(), SchoolClass.name.asc())
            .all()
        ),
    }


def get_database_backup_tables(connection):
    tables = list(Base.metadata.sorted_tables)
    table_names = {table.name for table in tables}

    if "schema_migrations" in inspect(connection).get_table_names() and "schema_migrations" not in table_names:
        metadata = MetaData()
        tables.insert(0, Table("schema_migrations", metadata, autoload_with=connection))

    return tables


def serialize_database_value(value):
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, time):
        return value.isoformat()

    return value


def deserialize_database_value(column, value):
    if value is None:
        return None

    if isinstance(column.type, SQLDateTime):
        return datetime.fromisoformat(value)

    if isinstance(column.type, SQLDate):
        return date.fromisoformat(value)

    if isinstance(column.type, SQLTime):
        return time.fromisoformat(value)

    return value


def build_database_backup_payload():
    generated_at = current_app_datetime()

    with engine.connect() as connection:
        tables = get_database_backup_tables(connection)
        payload = {
            "format": DATABASE_BACKUP_FORMAT,
            "version": DATABASE_BACKUP_VERSION,
            "generated_at": generated_at.isoformat(),
            "tables": {},
            "table_order": [table.name for table in tables],
        }

        for table in tables:
            rows = []

            for row in connection.execute(select(table)).mappings():
                rows.append({
                    column.name: serialize_database_value(row[column.name])
                    for column in table.columns
                })

            payload["tables"][table.name] = rows

    return payload


def load_database_backup_payload(uploaded_file):
    backup_bytes = uploaded_file.read(MAX_DATABASE_BACKUP_BYTES + 1)

    if len(backup_bytes) > MAX_DATABASE_BACKUP_BYTES:
        raise ValueError("Backup file is too large. Maximum allowed size is 200 MB.")

    try:
        payload = json.loads(backup_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Backup file must be a valid Henokh JSON backup.") from error

    if payload.get("format") != DATABASE_BACKUP_FORMAT:
        raise ValueError("Backup file format is not recognized.")

    if payload.get("version") != DATABASE_BACKUP_VERSION:
        raise ValueError("Backup file version is not supported.")

    if not isinstance(payload.get("tables"), dict):
        raise ValueError("Backup file does not contain database tables.")

    return payload


def restore_database_backup_payload(payload):
    restored_rows = 0
    repaired_class_students = 0

    with engine.begin() as connection:
        tables = get_database_backup_tables(connection)
        missing_tables = [
            table.name
            for table in tables
            if table.name != "schema_migrations" and table.name not in payload["tables"]
        ]

        if missing_tables:
            raise ValueError(f"Backup file is missing table data: {', '.join(missing_tables)}")

        connection.execute(text("SET FOREIGN_KEY_CHECKS=0"))

        try:
            for table in reversed(tables):
                connection.execute(table.delete())

            for table in tables:
                rows = payload["tables"].get(table.name, [])

                if not isinstance(rows, list):
                    raise ValueError(f"Backup table {table.name} is invalid.")

                restored_rows += len(rows)

                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError(f"Backup table {table.name} contains invalid row data.")

                    values = {
                        column.name: deserialize_database_value(column, row.get(column.name))
                        for column in table.columns
                        if column.name in row
                    }
                    connection.execute(table.insert().values(**values))
        finally:
            connection.execute(text("SET FOREIGN_KEY_CHECKS=1"))

        repaired_class_students = repair_presence_structure_after_restore(connection)

    return {
        "restored_rows": restored_rows,
        "repaired_class_students": repaired_class_students,
    }


def repair_presence_structure_after_restore(connection):
    class_ids = [
        row[0]
        for row in connection.execute(text("""
            SELECT id
            FROM classes
            ORDER BY id
            LIMIT 2
        """))
    ]

    active_student_count = connection.execute(text("""
        SELECT COUNT(*)
        FROM students
        WHERE deleted_at IS NULL
    """)).scalar()

    if not active_student_count:
        return 0

    if not class_ids:
        now = current_app_datetime()
        result = connection.execute(
            text("""
                INSERT INTO classes (name, class_code, created_at, updated_at)
                VALUES (:name, :class_code, :created_at, :updated_at)
            """),
            {
                "name": "Restored Class",
                "class_code": "RESTORED",
                "created_at": now,
                "updated_at": now,
            }
        )
        class_ids = [result.lastrowid]

    if len(class_ids) != 1:
        return 0

    class_student_count = connection.execute(
        text("SELECT COUNT(*) FROM class_students")
    ).scalar()

    if class_student_count:
        return 0

    result = connection.execute(
        text("""
            INSERT IGNORE INTO class_students (class_id, student_id)
            SELECT :class_id, id
            FROM students
            WHERE deleted_at IS NULL
        """),
        {"class_id": class_ids[0]}
    )

    return result.rowcount or 0


def build_presence_dashboard_context(session):
    today = current_app_datetime().date()
    selected_class_id = request.args.get("class_id", type=int)
    month_value = request.args.get("month", "")

    try:
        month_start = datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
    except ValueError:
        month_start = today.replace(day=1)

    presence_classes = (
        session.query(SchoolClass)
        .options(selectinload(SchoolClass.students))
        .order_by(SchoolClass.deleted_at.asc(), SchoolClass.name.asc())
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
                "is_today": day == today,
                "summary": summaries.get(day, {"presence": 0, "late": 0, "absen": 0})
            }
            for day in week
        ])

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
    }


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
    allowed_sections = {"overview", "students", "teachers", "classes", "presence", "settings"}

    if active_section == "users":
        active_section = "settings"

    if active_section not in allowed_sections:
        active_section = "overview"

    session = SessionLocal()

    try:
        page, per_page = get_pagination_params()
        search_query = get_search_query()
        search_pattern = f"%{search_query}%"
        student_query = (
            session.query(Student)
            .filter(Student.deleted_at.is_(None))
            .order_by(Student.created_at.desc())
        )
        teacher_query = (
            session.query(Teacher)
            .filter(Teacher.deleted_at.is_(None))
            .order_by(Teacher.created_at.desc())
        )
        class_query = (
            session.query(SchoolClass)
            .options(selectinload(SchoolClass.teacher))
            .filter(SchoolClass.deleted_at.is_(None))
            .order_by(SchoolClass.created_at.desc())
        )
        user_query = session.query(User).order_by(User.created_at.desc())

        if search_query:
            student_query = student_query.filter(or_(
                Student.name.ilike(search_pattern),
                Student.nim.ilike(search_pattern)
            ))
            teacher_query = teacher_query.filter(or_(
                Teacher.name.ilike(search_pattern),
                Teacher.nip.ilike(search_pattern)
            ))
            class_query = class_query.filter(or_(
                SchoolClass.name.ilike(search_pattern),
                SchoolClass.class_code.ilike(search_pattern),
                SchoolClass.teacher.has(Teacher.name.ilike(search_pattern))
            ))
            user_query = user_query.filter(User.username.ilike(search_pattern))

        student_pagination = paginate_query(student_query, page, per_page, search_query)
        teacher_pagination = paginate_query(teacher_query, page, per_page, search_query)
        class_pagination = paginate_query(class_query, page, per_page, search_query)
        user_pagination = paginate_query(user_query, page, per_page, search_query)
        student_count = student_pagination["total"]
        teacher_count = teacher_pagination["total"]
        class_count = class_pagination["total"]
        user_count = user_pagination["total"]
        students = student_pagination["items"]
        teachers = teacher_pagination["items"]
        classes = class_pagination["items"]
        users = user_pagination["items"]
        presence_context = (
            build_presence_dashboard_context(session)
            if active_section == "presence"
            else None
        )
        archived_cleanup_counts = (
            build_archived_cleanup_counts(session)
            if active_section == "settings"
            else None
        )
        archived_restore_data = (
            build_archived_restore_data(session)
            if active_section == "settings"
            else None
        )

        return render_template(
            "dashboard.html",
            students=students,
            teachers=teachers,
            classes=classes,
            users=users,
            student_count=student_count,
            teacher_count=teacher_count,
            class_count=class_count,
            user_count=user_count,
            student_pagination=student_pagination,
            teacher_pagination=teacher_pagination,
            class_pagination=class_pagination,
            user_pagination=user_pagination,
            active_section=active_section,
            current_user_id=flask_session.get("user_id"),
            username=flask_session.get("username"),
            anti_spoof_enabled=is_anti_spoof_enabled(),
            presence_context=presence_context,
            archived_cleanup_counts=archived_cleanup_counts,
            archived_restore_data=archived_restore_data,
            debug_model_result=get_latest_debug_model_result(),
            debug_model_jobs=get_debug_model_jobs()
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
    page = parse_optional_int(request.form.get("page")) or 1
    per_page = parse_optional_int(request.form.get("per_page")) or 10
    search_query = (request.form.get("q") or "").strip()

    if not class_id or not student_id or not attendance_date or status not in {"presence", "late", "absen"}:
        return redirect(url_for("dashboard", section="presence", class_id=class_id or "", month=month, page=page, per_page=per_page, q=search_query))

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
        "attendance_detail",
        class_id=class_id,
        attendance_date=attendance_date.isoformat(),
        month=month,
        page=page,
        per_page=per_page,
        q=search_query
    ))


@app.route("/attendance/delete", methods=["POST"])
@login_required
def delete_attendance():
    class_id = parse_optional_int(request.form.get("class_id"))
    student_id = parse_optional_int(request.form.get("student_id"))
    attendance_date = parse_date_field(request.form.get("attendance_date"))
    month = request.form.get("month") or (attendance_date.strftime("%Y-%m") if attendance_date else "")
    page = parse_optional_int(request.form.get("page")) or 1
    per_page = parse_optional_int(request.form.get("per_page")) or 10
    search_query = (request.form.get("q") or "").strip()

    if not class_id or not student_id or not attendance_date:
        return redirect(url_for("dashboard", section="presence", class_id=class_id or "", month=month, page=page, per_page=per_page, q=search_query))

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

        if attendance:
            session.delete(attendance)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for(
        "attendance_detail",
        class_id=class_id,
        attendance_date=attendance_date.isoformat(),
        month=month,
        page=page,
        per_page=per_page,
        q=search_query
    ))


@app.route("/attendance/detail")
@login_required
def attendance_detail():
    class_id = request.args.get("class_id", type=int)
    attendance_date = parse_date_field(request.args.get("attendance_date"))
    month = request.args.get("month") or (attendance_date.strftime("%Y-%m") if attendance_date else "")
    page, per_page = get_pagination_params()
    search_query = get_search_query()
    search_pattern = f"%{search_query}%"

    if not class_id or not attendance_date:
        return redirect(url_for("dashboard", section="presence", month=month))

    session = SessionLocal()

    try:
        school_class = (
            session.query(SchoolClass)
            .options(selectinload(SchoolClass.students))
            .filter_by(id=class_id)
            .one_or_none()
        )

        if school_class is None:
            return redirect(url_for("dashboard", section="presence", month=month))

        student_query = (
            session.query(Student)
            .join(class_students, Student.id == class_students.c.student_id)
            .filter(class_students.c.class_id == class_id)
            .order_by(Student.name.asc())
        )

        if search_query:
            student_query = student_query.filter(or_(
                Student.name.ilike(search_pattern),
                Student.nim.ilike(search_pattern)
            ))

        student_pagination = paginate_query(student_query, page, per_page, search_query)
        page_student_ids = [student.id for student in student_pagination["items"]]

        attendance_by_student_id = {
            attendance.student_id: attendance
            for attendance in session.query(Attendance)
            .filter(
                Attendance.class_id == class_id,
                Attendance.attendance_date == attendance_date,
                Attendance.student_id.in_(page_student_ids)
            )
            .all()
        } if page_student_ids else {}

        detail_rows = [
            {
                "student": student,
                "attendance": attendance_by_student_id.get(student.id)
            }
            for student in student_pagination["items"]
        ]

        return render_template(
            "attendance_detail.html",
            active_section="presence",
            username=flask_session.get("username"),
            school_class=school_class,
            attendance_date=attendance_date,
            month=month,
            detail_rows=detail_rows,
            pagination=student_pagination
        )
    finally:
        SessionLocal.remove()


@app.route("/settings/anti-spoof", methods=["POST"])
@login_required
def update_anti_spoof_setting():
    set_anti_spoof_enabled(request.form.get("anti_spoof_enabled") == "on")
    return redirect(url_for("dashboard", section="settings"))


@app.route("/settings/database-backup", methods=["POST"])
@login_required
def backup_database():
    payload = build_database_backup_payload()
    backup_bytes = json.dumps(payload, indent=2).encode("utf-8")
    timestamp = current_app_datetime().strftime("%Y%m%d_%H%M%S")
    filename = f"henokh_db_backup_{timestamp}.json"

    return send_file(
        io.BytesIO(backup_bytes),
        mimetype="application/json",
        as_attachment=True,
        download_name=filename
    )


@app.route("/settings/database-restore", methods=["POST"])
@login_required
def restore_database():
    uploaded_file = request.files.get("database_backup")

    if uploaded_file is None or not uploaded_file.filename:
        flash("Choose a database backup file before restoring.", "error")
        return redirect(url_for("dashboard", section="settings"))

    try:
        payload = load_database_backup_payload(uploaded_file)
        restore_result = restore_database_backup_payload(payload)
        message = f"Database restored from backup. {restore_result['restored_rows']} rows imported."

        if restore_result["repaired_class_students"]:
            message += f" Assigned {restore_result['repaired_class_students']} students to the restored class."

        flash(message, "success")
    except ValueError as error:
        flash(str(error), "error")
    except Exception as error:
        flash(f"Database restore failed: {error}", "error")

    return redirect(url_for("dashboard", section="settings"))


def safe_percentage(value, total):
    return round((value / total) * 100, 2) if total else 0


def normalize_debug_name(value):
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def trim_debug_model_jobs():
    if len(DEBUG_MODEL_JOBS) <= 10:
        return

    ordered_jobs = sorted(
        DEBUG_MODEL_JOBS.values(),
        key=lambda job: job.get("started_at") or "",
        reverse=True
    )
    keep_ids = {job["id"] for job in ordered_jobs[:10]}

    for job_id in list(DEBUG_MODEL_JOBS):
        if job_id not in keep_ids:
            DEBUG_MODEL_JOBS.pop(job_id, None)


def get_debug_model_jobs():
    with DEBUG_MODEL_JOBS_LOCK:
        return sorted(
            (dict(job) for job in DEBUG_MODEL_JOBS.values()),
            key=lambda job: job.get("started_at") or "",
            reverse=True
        )[:5]


def get_latest_debug_model_result():
    for job in get_debug_model_jobs():
        if job.get("status") == "completed" and job.get("result"):
            return job["result"]

    return None


def start_debug_model_job(zip_bytes, uploaded_filename):
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "running",
        "filename": uploaded_filename or "-",
        "started_at": current_app_datetime().isoformat(timespec="seconds"),
    }

    with DEBUG_MODEL_JOBS_LOCK:
        DEBUG_MODEL_JOBS[job_id] = job
        trim_debug_model_jobs()

    thread = threading.Thread(
        target=run_debug_model_job,
        args=(job_id, zip_bytes),
        daemon=True
    )
    thread.start()
    return job


def run_debug_model_job(job_id, zip_bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
            result = evaluate_debug_model_zip(zip_file)

        status_update = {
            "status": "completed",
            "finished_at": current_app_datetime().isoformat(timespec="seconds"),
            "result": result,
        }
    except Exception as error:
        status_update = {
            "status": "failed",
            "finished_at": current_app_datetime().isoformat(timespec="seconds"),
            "error": str(error),
        }

    with DEBUG_MODEL_JOBS_LOCK:
        if job_id in DEBUG_MODEL_JOBS:
            DEBUG_MODEL_JOBS[job_id].update(status_update)


def parse_debug_model_image_name(filename):
    path = PurePosixPath(filename)
    image_name = path.name

    if not image_name or image_name.startswith("."):
        return None

    image_path = PurePosixPath(image_name.lower())

    if image_path.suffix not in BULK_STUDENT_PHOTO_EXTENSIONS:
        return None

    stem = image_name[:len(image_name) - len(path.suffix)]
    tokens = [token.strip() for token in stem.split("_") if token.strip()]
    lowered_tokens = [token.casefold() for token in tokens]

    if len(tokens) < 3:
        raise ValueError("filename must use CLASS_NAME_NIM*")

    class_token = lowered_tokens[0]

    if class_token in {"spoof", "fake"}:
        expected_liveness = "spoof"
    elif class_token in {"real", "live"}:
        expected_liveness = "real"
    else:
        raise ValueError("CLASS must be real or spoof")

    nim_index = None

    for index in range(2, len(tokens)):
        if tokens[index].isdigit():
            nim_index = index
            break

    if nim_index is None:
        raise ValueError("filename must use CLASS_NAME_NIM* with numeric NIM")

    name = format_person_name(" ".join(tokens[1:nim_index]))
    nim = tokens[nim_index]

    return {
        "filename": filename,
        "class_name": expected_liveness,
        "name": name,
        "nim": nim,
        "expected_liveness": expected_liveness,
    }


def find_debug_model_images(zip_file):
    images = []
    errors = []

    for zip_info in zip_file.infolist():
        if zip_info.is_dir():
            continue

        path = PurePosixPath(zip_info.filename)

        if path.parts and path.parts[0] == "__MACOSX":
            continue

        try:
            parsed = parse_debug_model_image_name(zip_info.filename)
        except ValueError as error:
            errors.append(f"{zip_info.filename}: {error}")
            continue

        if parsed is None:
            continue

        images.append((zip_info, parsed))

    return images, errors


def select_best_debug_detection(detections):
    live_detections = [
        detection
        for detection in detections
        if (detection.get("liveness") or {}).get("label") == "real"
    ]

    return select_best_registration_detection(live_detections or detections)


def predicted_liveness_label(detection):
    if detection is None:
        return "spoof"

    liveness = detection.get("liveness") or {}
    label = liveness.get("label")

    if label in {"real", "spoof"}:
        return label

    real_score = (liveness.get("scores") or {}).get("real", 0)
    threshold = liveness.get("threshold", SPOOF_REAL_THRESHOLD)
    return "real" if real_score >= threshold else "spoof"


def evaluate_debug_model_zip(zip_file):
    entries, structure_errors = find_debug_model_images(zip_file)

    if not entries:
        raise ValueError("No standard image files found. Use filenames like REAL_STUDENT_NAME_12345_01.jpg or SPOOF_STUDENT_NAME_12345_01.jpg.")

    session = SessionLocal()

    try:
        known_students = {
            nim.casefold(): normalize_debug_name(name)
            for nim, name in session.query(Student.nim, Student.name)
            .filter(Student.deleted_at.is_(None), Student.face_embeddings.is_not(None))
            .all()
        }
    finally:
        SessionLocal.remove()

    totals = {
        "processed": 0,
        "failed": 0,
        "unlabeled_liveness": 0,
        "spoof_total": 0,
        "spoof_prevented": 0,
        "spoof_false_accepted": 0,
        "real_total": 0,
        "real_accepted": 0,
        "real_false_alarm": 0,
        "identity_total": 0,
        "identity_correct": 0,
        "identity_wrong": 0,
        "unknown_student": 0,
    }
    rows = []

    for zip_info, expected in sorted(entries, key=lambda item: item[0].filename):
        row = {
            "file": expected["filename"],
            "class_name": expected["class_name"],
            "expected_name": expected["name"],
            "expected_nim": expected["nim"],
            "expected_liveness": expected["expected_liveness"] or "unlabeled",
        }

        if zip_info.file_size > DEBUG_MODEL_IMAGE_BYTES:
            row["status"] = "failed"
            row["error"] = "image file is larger than 15 MB"
            totals["failed"] += 1
            rows.append(row)
            continue

        try:
            image_bytes = zip_file.read(zip_info)
            frame = decode_image_bytes(image_bytes)

            if frame is None:
                raise ValueError("Invalid image")

            ai_result = analyze_frame(
                encode_image_data(frame),
                anti_spoof_enabled=True,
                include_embeddings=True
            )
            detections = identify_detected_faces(ai_result.get("detections") or [])
            detection = select_best_debug_detection(detections)
            predicted_label = predicted_liveness_label(detection)
            identity = (detection or {}).get("identity") or {}
            predicted_nim = identity.get("nim") if identity.get("matched") else None
            predicted_name = identity.get("name") if identity.get("matched") else None

            row.update({
                "status": "processed",
                "detections": len(detections),
                "predicted_liveness": predicted_label,
                "predicted_name": predicted_name or "-",
                "predicted_nim": predicted_nim or "-",
                "identity_similarity": identity.get("similarity", "-"),
            })
            totals["processed"] += 1

            if expected["expected_liveness"] == "spoof":
                totals["spoof_total"] += 1

                if predicted_label == "spoof":
                    totals["spoof_prevented"] += 1
                else:
                    totals["spoof_false_accepted"] += 1
            elif expected["expected_liveness"] == "real":
                totals["real_total"] += 1

                if predicted_label == "real":
                    totals["real_accepted"] += 1
                else:
                    totals["real_false_alarm"] += 1
            else:
                totals["unlabeled_liveness"] += 1

            expected_nim_key = expected["nim"].casefold()
            expected_name_key = normalize_debug_name(expected["name"])
            known_name_key = known_students.get(expected_nim_key)

            if known_name_key is None or known_name_key != expected_name_key:
                totals["unknown_student"] += 1
                row["identity_result"] = "unknown expected name/NIM"
            elif expected["expected_liveness"] != "spoof":
                totals["identity_total"] += 1
                predicted_nim_matches = (
                    (predicted_nim or "").casefold() == expected_nim_key
                )
                predicted_name_matches = (
                    normalize_debug_name(predicted_name) == expected_name_key
                )

                if predicted_nim_matches and predicted_name_matches:
                    totals["identity_correct"] += 1
                    row["identity_result"] = "correct"
                else:
                    totals["identity_wrong"] += 1
                    row["identity_result"] = "wrong"
            else:
                row["identity_result"] = "skipped for spoof sample"
        except (AIServiceError, ValueError) as error:
            row["status"] = "failed"
            row["error"] = str(error)
            totals["failed"] += 1
        except Exception as error:
            row["status"] = "failed"
            row["error"] = f"failed to evaluate ({error})"
            totals["failed"] += 1

        rows.append(row)

    report_path = write_debug_model_report(rows, structure_errors, totals)

    return {
        "processed": totals["processed"],
        "failed": totals["failed"],
        "spoof_total": totals["spoof_total"],
        "spoof_prevented": totals["spoof_prevented"],
        "spoof_false_accepted": totals["spoof_false_accepted"],
        "spoof_prevented_pct": safe_percentage(totals["spoof_prevented"], totals["spoof_total"]),
        "spoof_false_accepted_pct": safe_percentage(totals["spoof_false_accepted"], totals["spoof_total"]),
        "real_total": totals["real_total"],
        "real_accepted": totals["real_accepted"],
        "real_false_alarm": totals["real_false_alarm"],
        "real_accepted_pct": safe_percentage(totals["real_accepted"], totals["real_total"]),
        "real_false_alarm_pct": safe_percentage(totals["real_false_alarm"], totals["real_total"]),
        "identity_total": totals["identity_total"],
        "identity_correct": totals["identity_correct"],
        "identity_wrong": totals["identity_wrong"],
        "identity_correct_pct": safe_percentage(totals["identity_correct"], totals["identity_total"]),
        "identity_wrong_pct": safe_percentage(totals["identity_wrong"], totals["identity_total"]),
        "unlabeled_liveness": totals["unlabeled_liveness"],
        "unknown_student": totals["unknown_student"],
        "structure_errors": len(structure_errors),
        "report_path": str(report_path.relative_to(BASE_DIR)),
    }


def write_debug_model_report(rows, structure_errors, totals):
    DEBUG_MODEL_REPORT_DIR.mkdir(exist_ok=True)
    generated_at = current_app_datetime()
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S_%f")
    report_path = DEBUG_MODEL_REPORT_DIR / f"debug_model_accuracy_{timestamp}.csv"
    fieldnames = [
        "file",
        "status",
        "class_name",
        "expected_liveness",
        "predicted_liveness",
        "expected_name",
        "predicted_name",
        "expected_nim",
        "predicted_nim",
        "identity_result",
        "identity_similarity",
        "detections",
        "error",
    ]

    with report_path.open("w", newline="", encoding="utf-8") as report_file:
        writer = csv.writer(report_file)
        writer.writerow(["Debug Model Evaluation"])
        writer.writerow(["generated_at", generated_at.isoformat()])
        writer.writerow(["face_match_threshold", FACE_MATCH_THRESHOLD])
        writer.writerow(["spoof_real_threshold", SPOOF_REAL_THRESHOLD])
        writer.writerow([])
        writer.writerow(["metric", "count", "total", "percentage"])
        writer.writerow([
            "spoof_prevented",
            totals["spoof_prevented"],
            totals["spoof_total"],
            safe_percentage(totals["spoof_prevented"], totals["spoof_total"]),
        ])
        writer.writerow([
            "spoof_false_accepted",
            totals["spoof_false_accepted"],
            totals["spoof_total"],
            safe_percentage(totals["spoof_false_accepted"], totals["spoof_total"]),
        ])
        writer.writerow([
            "real_accepted",
            totals["real_accepted"],
            totals["real_total"],
            safe_percentage(totals["real_accepted"], totals["real_total"]),
        ])
        writer.writerow([
            "real_false_alarm",
            totals["real_false_alarm"],
            totals["real_total"],
            safe_percentage(totals["real_false_alarm"], totals["real_total"]),
        ])
        writer.writerow([
            "identity_correct",
            totals["identity_correct"],
            totals["identity_total"],
            safe_percentage(totals["identity_correct"], totals["identity_total"]),
        ])
        writer.writerow([
            "identity_wrong",
            totals["identity_wrong"],
            totals["identity_total"],
            safe_percentage(totals["identity_wrong"], totals["identity_total"]),
        ])
        writer.writerow(["processed", totals["processed"], "", ""])
        writer.writerow(["failed", totals["failed"], "", ""])
        writer.writerow(["unlabeled_liveness", totals["unlabeled_liveness"], "", ""])
        writer.writerow(["unknown_student", totals["unknown_student"], "", ""])
        writer.writerow(["structure_errors", len(structure_errors), "", ""])
        writer.writerow([])

        if structure_errors:
            writer.writerow(["filename_errors"])

            for error in structure_errors:
                writer.writerow([error])

            writer.writerow([])

        writer.writerow(["details"])
        dict_writer = csv.DictWriter(report_file, fieldnames=fieldnames, extrasaction="ignore")
        dict_writer.writeheader()

        for row in rows:
            dict_writer.writerow(row)

    return report_path


@app.route("/settings/debug-model-evaluation", methods=["POST"])
@login_required
def debug_model_evaluation():
    uploaded_file = request.files.get("debug_model_zip")

    if uploaded_file is None or not uploaded_file.filename:
        flash("Choose a debug model ZIP before running evaluation.", "error")
        return redirect(url_for("dashboard", section="settings"))

    if not uploaded_file.filename.lower().endswith(".zip"):
        flash("Debug model evaluation only accepts .zip files.", "error")
        return redirect(url_for("dashboard", section="settings"))

    zip_bytes = uploaded_file.read(DEBUG_MODEL_ZIP_BYTES + 1)

    if len(zip_bytes) > DEBUG_MODEL_ZIP_BYTES:
        flash("ZIP file is too large. Maximum allowed size is 100 MB.", "error")
        return redirect(url_for("dashboard", section="settings"))

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)):
            pass
    except zipfile.BadZipFile:
        flash("Uploaded file is not a valid ZIP archive.", "error")
        return redirect(url_for("dashboard", section="settings"))

    job = start_debug_model_job(zip_bytes, uploaded_file.filename)
    flash(
        f"Debug evaluation started in the background. Job {job['id']} is processing and will write a CSV report when finished.",
        "success"
    )

    return redirect(url_for("dashboard", section="settings"))


@app.route("/settings/cleanup-archived", methods=["POST"])
@login_required
def cleanup_archived_data():
    session = SessionLocal()

    try:
        counts = build_archived_cleanup_counts(session)
        archived_teacher_ids = [
            teacher_id
            for (teacher_id,) in session.query(Teacher.id)
            .filter(Teacher.deleted_at.is_not(None))
            .all()
        ]

        if archived_teacher_ids:
            session.query(SchoolClass).filter(
                SchoolClass.teacher_id.in_(archived_teacher_ids)
            ).update(
                {SchoolClass.teacher_id: None},
                synchronize_session=False
            )

        session.query(SchoolClass).filter(SchoolClass.deleted_at.is_not(None)).delete(synchronize_session=False)
        session.query(Student).filter(Student.deleted_at.is_not(None)).delete(synchronize_session=False)
        session.query(Teacher).filter(Teacher.deleted_at.is_not(None)).delete(synchronize_session=False)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    total = counts["students"] + counts["teachers"] + counts["classes"]
    return redirect(url_for("dashboard", section="settings", cleanup=f"deleted-{total}"))


@app.route("/settings/restore-archived", methods=["POST"])
@login_required
def restore_archived_data():
    data_type = (request.form.get("data_type") or "").strip()
    model_by_type = {
        "students": Student,
        "teachers": Teacher,
        "classes": SchoolClass,
    }
    model = model_by_type.get(data_type)

    if model is None:
        return redirect(url_for("dashboard", section="settings"))

    session = SessionLocal()

    try:
        restored_count = (
            session.query(model)
            .filter(model.deleted_at.is_not(None))
            .update({model.deleted_at: None}, synchronize_session=False)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="settings", restored=f"{data_type}-{restored_count}"))


@app.route("/settings/restore-selected-archived", methods=["POST"])
@login_required
def restore_selected_archived_data():
    data_type = (request.form.get("data_type") or "").strip()
    selected_ids = [
        int(item_id)
        for item_id in request.form.getlist("item_ids")
        if item_id.isdigit()
    ]
    model_by_type = {
        "students": Student,
        "teachers": Teacher,
        "classes": SchoolClass,
    }
    model = model_by_type.get(data_type)

    if model is None or not selected_ids:
        return redirect(url_for("dashboard", section="settings"))

    session = SessionLocal()

    try:
        restored_count = (
            session.query(model)
            .filter(model.id.in_(selected_ids), model.deleted_at.is_not(None))
            .update({model.deleted_at: None}, synchronize_session=False)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="settings", restored=f"{data_type}-{restored_count}"))


@app.route("/teachers", methods=["POST"])
@login_required
def create_teacher():
    teacher_id = parse_optional_int(request.form.get("teacher_id"))
    name = request.form.get("name", "").strip()
    nip = request.form.get("nip", "").strip()

    if not name or not nip:
        return redirect(url_for("dashboard", section="teachers", error="teacher"))

    if not is_digits_only(nip):
        return redirect(url_for("dashboard", section="teachers", error="teacher"))

    session = SessionLocal()

    try:
        teacher = session.get(Teacher, teacher_id) if teacher_id else None

        if teacher_id and teacher is None:
            return redirect(url_for("dashboard", section="teachers"))

        if teacher_id:
            duplicate_teacher = (
                session.query(Teacher)
                .filter(Teacher.nip == nip, Teacher.id != teacher_id)
                .one_or_none()
            )

            if duplicate_teacher:
                return redirect(url_for("edit_teacher", teacher_id=teacher_id, error="teacher"))
        else:
            teacher = session.query(Teacher).filter_by(nip=nip).one_or_none()

        if teacher is None:
            teacher = Teacher(name=name, nip=nip)
            session.add(teacher)
        else:
            teacher.name = name
            teacher.nip = nip

        teacher.deleted_at = None
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
        return redirect(url_for("dashboard", section="settings", error="user"))

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

    return redirect(url_for("dashboard", section="settings"))


@app.route("/classes", methods=["POST"])
@login_required
def create_class():
    class_id = parse_optional_int(request.form.get("class_id"))
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
        school_class = session.get(SchoolClass, class_id) if class_id else None

        if class_id and school_class is None:
            return redirect(url_for("dashboard", section="classes"))

        duplicate_class = (
            session.query(SchoolClass)
            .filter(SchoolClass.class_code == class_code, SchoolClass.id != class_id)
            .one_or_none()
            if class_id
            else session.query(SchoolClass).filter_by(class_code=class_code).one_or_none()
        )

        if duplicate_class:
            if class_id:
                session.rollback()
                return redirect(url_for("edit_class", class_id=class_id, error="class"))

            school_class = duplicate_class

        if school_class is None:
            school_class = SchoolClass(name=name, class_code=class_code)
            session.add(school_class)
        else:
            school_class.name = name
            school_class.class_code = class_code

        school_class.deleted_at = None
        school_class.start_time = start_time
        school_class.end_time = end_time
        school_class.start_presence = start_presence
        school_class.end_presence = end_presence
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
            school_class.deleted_at = current_app_datetime()
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="classes"))


@app.route("/classes/<int:class_id>/restore", methods=["POST"])
@login_required
def restore_class(class_id):
    session = SessionLocal()

    try:
        school_class = session.get(SchoolClass, class_id)

        if school_class:
            school_class.deleted_at = None
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="settings"))


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    session = SessionLocal()

    try:
        student = session.get(Student, student_id)

        if student:
            student.deleted_at = current_app_datetime()
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="students"))


@app.route("/students/<int:student_id>/restore", methods=["POST"])
@login_required
def restore_student(student_id):
    session = SessionLocal()

    try:
        student = session.get(Student, student_id)

        if student:
            student.deleted_at = None
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="settings"))


@app.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@login_required
def delete_teacher(teacher_id):
    session = SessionLocal()

    try:
        teacher = session.get(Teacher, teacher_id)

        if teacher:
            teacher.deleted_at = current_app_datetime()
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="teachers"))


@app.route("/teachers/<int:teacher_id>/restore", methods=["POST"])
@login_required
def restore_teacher(teacher_id):
    session = SessionLocal()

    try:
        teacher = session.get(Teacher, teacher_id)

        if teacher:
            teacher.deleted_at = None
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()

    return redirect(url_for("dashboard", section="settings"))


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    if user_id == flask_session.get("user_id"):
        return redirect(url_for("dashboard", section="settings"))

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

    return redirect(url_for("dashboard", section="settings"))


@app.route("/students/new")
@login_required
def new_student():
    return render_template("student_form.html", active_section="students", student=None)


@app.route("/students/<int:student_id>/edit")
@login_required
def edit_student(student_id):
    session = SessionLocal()

    try:
        student = (
            session.query(Student)
            .filter(Student.id == student_id, Student.deleted_at.is_(None))
            .one_or_none()
        )

        if student is None:
            return redirect(url_for("dashboard", section="students"))

        return render_template("student_form.html", active_section="students", student=student)
    finally:
        SessionLocal.remove()


@app.route("/students/bulk-import", methods=["POST"])
@login_required
def bulk_import_students():
    uploaded_file = request.files.get("student_zip")

    if uploaded_file is None or not uploaded_file.filename:
        flash("Choose a .zip file before importing students.", "error")
        return redirect(url_for("dashboard", section="students"))

    if not uploaded_file.filename.lower().endswith(".zip"):
        flash("Bulk student import only accepts .zip files.", "error")
        return redirect(url_for("dashboard", section="students"))

    zip_bytes = uploaded_file.read(MAX_BULK_STUDENT_ZIP_BYTES + 1)

    if len(zip_bytes) > MAX_BULK_STUDENT_ZIP_BYTES:
        flash("ZIP file is too large. Maximum allowed size is 100 MB.", "error")
        return redirect(url_for("dashboard", section="students"))

    try:
        zip_file = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        flash("Uploaded file is not a valid ZIP archive.", "error")
        return redirect(url_for("dashboard", section="students"))

    created_count = 0
    updated_count = 0
    warning_count = 0
    errors = []
    db_session = SessionLocal()

    try:
        with zip_file:
            student_photos, structure_errors = find_bulk_student_photos(zip_file)
            errors.extend(structure_errors)

            if not student_photos:
                flash("No students imported. Expected folders like data/12345 Student Name/student-photo.jpg.", "error")
                return redirect(url_for("dashboard", section="students"))

            for folder_name, zip_info in sorted(student_photos.items()):
                nim, name = parse_bulk_student_folder(folder_name)
                label = folder_name

                if not nim or not name:
                    errors.append(f"{label}: folder name must be 'NIM Name'")
                    continue

                if zip_info.file_size > MAX_BULK_STUDENT_PHOTO_BYTES:
                    errors.append(f"{label}: photo file is larger than 15 MB")
                    continue

                try:
                    image_bytes = zip_file.read(zip_info)
                    frame = decode_image_bytes(image_bytes)
                    face_embedding, embedding_warning = build_student_face_embedding(frame)
                    student, action = save_student_with_embedding(db_session, nim, name, face_embedding)
                    db_session.commit()

                    if action == "created":
                        created_count += 1
                    else:
                        updated_count += 1

                    if embedding_warning:
                        warning_count += 1
                except (AIServiceError, ValueError) as error:
                    db_session.rollback()
                    errors.append(f"{label}: {error}")
                except Exception as error:
                    db_session.rollback()
                    errors.append(f"{label}: failed to import ({error})")
    finally:
        SessionLocal.remove()

    imported_count = created_count + updated_count
    summary = f"Bulk import complete: {created_count} created, {updated_count} updated"

    if warning_count:
        summary += f", {warning_count} saved without face embedding"

    summary += f", {len(errors)} failed."
    flash(summary, "success" if imported_count else "error")

    failure_log_path = write_bulk_student_failure_log(
        uploaded_file.filename,
        errors,
        created_count,
        updated_count
    )

    if failure_log_path:
        flash(f"Failure summary saved to {failure_log_path.relative_to(BASE_DIR)}.", "error")

    return redirect(url_for("dashboard", section="students"))


@app.route("/teachers/new")
@login_required
def new_teacher():
    return render_template("teacher_form.html", active_section="teachers", teacher=None)


@app.route("/teachers/<int:teacher_id>/edit")
@login_required
def edit_teacher(teacher_id):
    session = SessionLocal()

    try:
        teacher = (
            session.query(Teacher)
            .filter(Teacher.id == teacher_id, Teacher.deleted_at.is_(None))
            .one_or_none()
        )

        if teacher is None:
            return redirect(url_for("dashboard", section="teachers"))

        return render_template("teacher_form.html", active_section="teachers", teacher=teacher)
    finally:
        SessionLocal.remove()


@app.route("/users/new")
@login_required
def new_user():
    return render_template("user_form.html", active_section="settings")


@app.route("/classes/new")
@login_required
def new_class():
    session = SessionLocal()

    try:
        students = (
            session.query(Student)
            .filter(Student.deleted_at.is_(None))
            .order_by(Student.name.asc())
            .all()
        )
        teachers = (
            session.query(Teacher)
            .filter(Teacher.deleted_at.is_(None))
            .order_by(Teacher.name.asc())
            .all()
        )

        return render_template(
            "class_form.html",
            active_section="classes",
            school_class=None,
            students=students,
            teachers=teachers
        )
    finally:
        SessionLocal.remove()


@app.route("/classes/<int:class_id>/edit")
@login_required
def edit_class(class_id):
    session = SessionLocal()

    try:
        school_class = (
            session.query(SchoolClass)
            .options(selectinload(SchoolClass.teacher), selectinload(SchoolClass.students))
            .filter(SchoolClass.id == class_id, SchoolClass.deleted_at.is_(None))
            .one_or_none()
        )

        if school_class is None:
            return redirect(url_for("dashboard", section="classes"))

        selected_student_ids = {student.id for student in school_class.students}
        students = (
            session.query(Student)
            .filter((Student.deleted_at.is_(None)) | (Student.id.in_(selected_student_ids)))
            .order_by(Student.name.asc())
            .all()
        )
        teachers = (
            session.query(Teacher)
            .filter((Teacher.deleted_at.is_(None)) | (Teacher.id == school_class.teacher_id))
            .order_by(Teacher.name.asc())
            .all()
        )

        return render_template(
            "class_form.html",
            active_section="classes",
            school_class=school_class,
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
        classes = (
            session.query(SchoolClass)
            .filter(SchoolClass.deleted_at.is_(None))
            .order_by(SchoolClass.name.asc())
            .all()
        )
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


def decode_image_data(image_data):
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    image_bytes = base64.b64decode(image_data)
    return decode_image_bytes(image_bytes)


def decode_image_bytes(image_bytes):
    np_arr = np.frombuffer(image_bytes, np.uint8)
    return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)


def encode_image_data(frame):
    success, image_buffer = cv2.imencode(".jpg", frame)

    if not success:
        raise ValueError("Invalid face image")

    image_base64 = base64.b64encode(image_buffer.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{image_base64}"


def detection_area(detection):
    width = max(0, float(detection.get("width") or 0))
    height = max(0, float(detection.get("height") or 0))
    return width * height


def select_best_registration_detection(detections):
    if not detections:
        return None

    return max(
        detections,
        key=lambda detection: (
            float(detection.get("confidence") or 0),
            detection_area(detection)
        )
    )


def build_student_face_embedding(frame):
    if frame is None:
        raise ValueError("Invalid face image")

    anti_spoof_enabled = is_anti_spoof_enabled()
    ai_result = analyze_frame(
        encode_image_data(frame),
        anti_spoof_enabled=anti_spoof_enabled,
        include_embeddings=True
    )
    detections = ai_result.get("detections") or []

    detection = select_best_registration_detection(detections)

    if detection is None:
        raise ValueError("No face detected before saving")

    real_score = (detection.get("liveness") or {}).get("scores", {}).get("real", 0)

    if anti_spoof_enabled and real_score < SPOOF_REAL_THRESHOLD:
        raise ValueError("Face must pass real-person check before saving")

    if detection.get("embedding"):
        return detection["embedding"], None

    embedding_error = detection.get("embeddingError")

    if embedding_error:
        return None, embedding_error

    raise ValueError("Unable to build face embedding")


def parse_bulk_student_folder(folder_name):
    normalized_name = re.sub(r"\s+", " ", folder_name.strip())
    match = re.fullmatch(r"(\d+)\s+(.+)", normalized_name)

    if not match:
        return None, None

    return match.group(1), format_person_name(match.group(2))


def find_bulk_student_photos(zip_file):
    photos = {}
    errors = []

    for zip_info in zip_file.infolist():
        if zip_info.is_dir():
            continue

        path = PurePosixPath(zip_info.filename)
        parts = path.parts

        filename = PurePosixPath(parts[-1]).name.lower() if parts else ""
        photo_path = PurePosixPath(filename)
        is_allowed_photo = (
            len(parts) == 3
            and parts[0] == BULK_STUDENT_ROOT
            and photo_path.suffix in BULK_STUDENT_PHOTO_EXTENSIONS
        )

        if is_allowed_photo:
            folder_name = parts[1].strip()

            if not folder_name:
                errors.append(f"{zip_info.filename}: missing student folder name")
            elif folder_name in photos:
                errors.append(f"{zip_info.filename}: duplicate student folder")
            else:
                photos[folder_name] = zip_info
            continue

        if len(parts) > 1 and parts[0] == BULK_STUDENT_ROOT:
            errors.append(f"{zip_info.filename}: expected one image file inside data/NIM Name with jpg, jpeg, png, webp, or bmp extension")

    return photos, errors


def write_bulk_student_failure_log(uploaded_filename, errors, created_count, updated_count):
    if not errors:
        return None

    BULK_STUDENT_FAILURE_LOG_DIR.mkdir(exist_ok=True)
    generated_at = current_app_datetime()
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S_%f")
    log_path = BULK_STUDENT_FAILURE_LOG_DIR / f"bulk_student_failures_{timestamp}.txt"

    lines = [
        "Bulk Student Registration Failure Log",
        f"Generated at: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Source file: {uploaded_filename or '-'}",
        f"Created: {created_count}",
        f"Updated: {updated_count}",
        f"Failed: {len(errors)}",
    ]

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path


def save_student_with_embedding(session, nim, name, face_embedding, student=None):
    name = format_person_name(name)

    if student is None:
        student = session.query(Student).filter_by(nim=nim).one_or_none()

    if student is None:
        student = Student(name=name, nim=nim)
        session.add(student)
        action = "created"
    else:
        student.name = name
        student.nim = nim
        action = "updated"

    student.deleted_at = None

    if face_embedding is not None:
        student.set_face_embedding(face_embedding)

    return student, action


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


def identify_detected_faces(detections, class_id=None, record_attendance=False):
    if not detections:
        return detections

    session = SessionLocal()

    try:
        school_class = None

        if class_id:
            school_class = session.get(SchoolClass, class_id)
            students = (
                [
                    student
                    for student in school_class.students
                    if student.deleted_at is None
                ]
                if school_class and school_class.deleted_at is None
                else []
            )
        else:
            students = session.query(Student).filter(Student.deleted_at.is_(None)).all()

        known_students = [
            (student, np.asarray(student.face_embeddings, dtype="float32"))
            for student in students
            if student.face_embeddings
        ]

        if not known_students:
            return detections

        for detection in detections:
            if detection.get("embeddingError"):
                detection["identity"] = {
                    "matched": False,
                    "error": detection["embeddingError"]
                }
                continue

            if not detection.get("embedding"):
                continue

            embedding = np.asarray(detection["embedding"], dtype="float32")

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


def strip_detection_embeddings(detections):
    for detection in detections:
        detection.pop("embedding", None)
        detection.pop("embeddingError", None)

    return detections


@app.route("/students", methods=["POST"])
@login_required
def create_student():
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "message": "No student data received"}), 400

    name = data.get("name", "").strip()
    nim = str(data.get("nim", "")).strip()
    student_id = parse_optional_int(data.get("studentId"))
    image_data = data.get("image", "")

    if not name or not nim:
        return jsonify({
            "success": False,
            "message": "Name and NIM are required"
        }), 400

    if not is_digits_only(nim):
        return jsonify({
            "success": False,
            "message": "NIM must contain numbers only"
        }), 400

    session = SessionLocal()

    try:
        student = session.get(Student, student_id) if student_id else None

        if student_id and (student is None or student.deleted_at is not None):
            return jsonify({"success": False, "message": "Student not found"}), 404

        duplicate_student = (
            session.query(Student)
            .filter(Student.nim == nim, Student.id != student_id)
            .one_or_none()
            if student_id
            else session.query(Student).filter_by(nim=nim).one_or_none()
        )

        if duplicate_student:
            if student_id:
                return jsonify({"success": False, "message": "NIM is already used by another student"}), 400

            student = duplicate_student

        if student is None and not image_data:
            return jsonify({
                "success": False,
                "message": "Face image is required for new students"
            }), 400

        face_embedding = None
        embedding_warning = None

        if image_data:
            frame = decode_image_data(image_data)

            try:
                face_embedding, embedding_warning = build_student_face_embedding(frame)
            except AIServiceError as error:
                return jsonify({"success": False, "message": str(error)}), error.status_code
            except ValueError as error:
                return jsonify({"success": False, "message": str(error)}), 400

        student, action = save_student_with_embedding(session, nim, name, face_embedding, student=student)

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
        ai_result = analyze_frame(
            data["image"],
            anti_spoof_enabled=anti_spoof_enabled,
            include_embeddings=True
        )
        detections = ai_result.get("detections") or []
        detections = identify_detected_faces(
            detections,
            class_id=class_id,
            record_attendance=class_id is not None
        )
        detections = strip_detection_embeddings(detections)
    except AIServiceError as error:
        return jsonify({"success": False, "message": str(error)}), error.status_code

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
