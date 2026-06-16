import os
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker


def load_dotenv_file():
    env_path = os.path.join(os.path.dirname(__file__), ".env")

    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    for line in lines:
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_database_url():
    load_dotenv_file()

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        return database_url

    db_host = os.getenv("DB_HOST") or os.getenv("MARIADB_HOST")
    db_port = os.getenv("DB_PORT") or os.getenv("MARIADB_PORT") or "3306"
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD", "")

    missing = [
        key
        for key, value in {
            "DB_HOST or MARIADB_HOST": db_host,
            "DB_NAME": db_name,
            "DB_USER": db_user,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing MariaDB configuration: "
            + ", ".join(missing)
            + ". Run henokh_project.py install/run or create a .env file."
        )

    encoded_password = quote_plus(db_password)
    return (
        f"mysql+pymysql://{db_user}:{encoded_password}"
        f"@{db_host}:{db_port}/{db_name}?charset=utf8mb4"
    )


DATABASE_URL = get_database_url()
BASE_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = BASE_DIR / "migrations"


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
)


def init_db():
    from models.db_models import AppSetting, Attendance, SchoolClass, Student, Teacher, User  # noqa: F401

    Base.metadata.create_all(bind=engine)


def migrate_db():
    MIGRATIONS_DIR.mkdir(exist_ok=True)

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                version VARCHAR(255) NOT NULL UNIQUE,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

        applied_versions = {
            row[0]
            for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }

        for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = migration_path.name

            if version in applied_versions:
                print(f"Skipping migration: {version}")
                continue

            print(f"Applying migration: {version}")
            sql = migration_path.read_text(encoding="utf-8")

            for statement in split_sql_statements(sql):
                connection.execute(text(statement))

            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": version}
            )


def split_sql_statements(sql):
    statements = []
    current = []

    for line in sql.splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("--"):
            continue

        current.append(line)

        if stripped.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()

            if statement:
                statements.append(statement)

            current = []

    trailing_statement = "\n".join(current).strip()

    if trailing_statement:
        statements.append(trailing_statement)

    return statements


def seed_admin_user(username="admin", password="admin123"):
    from models.db_models import User

    session = SessionLocal()

    try:
        user = session.query(User).filter_by(username=username).one_or_none()

        if user is None:
            user = User(username=username)
            session.add(user)
            action = "created"
        else:
            action = "updated"

        user.set_password(password)
        session.commit()
        return action
    except Exception:
        session.rollback()
        raise
    finally:
        SessionLocal.remove()
