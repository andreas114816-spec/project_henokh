import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine
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


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
)


def init_db():
    from models.db_models import Student, User  # noqa: F401

    Base.metadata.create_all(bind=engine)


def migrate_db():
    init_db()


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
