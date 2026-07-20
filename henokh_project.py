import argparse
import ctypes
import os
import subprocess
import sys


# ============================================================
# CONFIG - EDIT THESE
# ============================================================

DISTRO_NAME = "Ubuntu-22.04"

PROJECT_FOLDER = "project_henokh"

GIT_REPO_URL = "https://github.com/andreas114816-spec/project_henokh.git"
AUTO_GIT_PULL = True

PYTHON_VERSION = "3.12.13"
PYTHON_PREFIX = f"/opt/python-{PYTHON_VERSION}"
PYTHON_BIN = f"{PYTHON_PREFIX}/bin/python3.12"

VENV_NAME = ".venv"

APP_PROGRAM_DIR = "app_program"
AI_PROGRAM_DIR = "ai_program"

GUNICORN_HOST = "0.0.0.0"
GUNICORN_PORT = "8000"
GUNICORN_WORKERS = "3"
GUNICORN_TIMEOUT = "600"

AI_SERVICE_HOST = "127.0.0.1"
AI_SERVICE_PORT = "8001"
AI_SERVICE_WORKERS = "1"

MARIADB_PORT_FILE = "/tmp/henokh_mariadb_port"

DB_NAME = "presence"
DB_USER = "user_admin"
DB_PASSWORD = "password123"

MOBILEFACENET_REPO_URL = "https://github.com/foamliu/MobileFaceNet.git"

LOG_FILE = os.path.join(os.environ.get("TEMP", os.getcwd()), "henokh_project.log")


# ============================================================
# BASIC HELPERS
# ============================================================

def write_log_file(message=""):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as file:
            file.write(f"{message}\n")
    except Exception:
        pass


def log(message=""):
    print(message, flush=True)
    write_log_file(message)


def pause_before_exit():
    if is_windows():
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass


def is_windows():
    return os.name == "nt"


def is_windows_admin():
    if not is_windows():
        return False

    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def relaunch_as_admin():
    if not is_windows():
        return False

    args = [arg for arg in sys.argv[1:] if arg != "--elevated"]
    params = subprocess.list2cmdline([os.path.abspath(__file__), "--elevated", *args])
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        params,
        os.getcwd(),
        1
    )

    return result > 32


def require_windows():
    if not is_windows():
        raise RuntimeError("This script must be run from Windows, not inside WSL/Linux.")


def require_admin():
    if not is_windows_admin():
        log("Administrator permission is required. Requesting Windows UAC elevation...")

        if relaunch_as_admin():
            log("Elevated process started. Continue in the Administrator window.")
            sys.exit(0)

        raise RuntimeError("Administrator permission request was cancelled or failed.")


def run_command(command, check=True):
    log()
    log(f"> {command}")

    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    for line in process.stdout:
        clean_line = line.rstrip()
        print(clean_line, flush=True)
        write_log_file(clean_line)

    process.wait()

    if check and process.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {process.returncode}: {command}")

    return process.returncode


def capture_command(command):
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    return result.stdout.strip(), result.stderr.strip(), result.returncode


def run_wsl_script(script, user=None, check=True):
    script = script.replace("\r\n", "\n").replace("\r", "\n")

    if user:
        command = [
            "wsl",
            "-d",
            DISTRO_NAME,
            "-u",
            user,
            "--",
            "bash",
            "-s"
        ]
    else:
        command = [
            "wsl",
            "-d",
            DISTRO_NAME,
            "--",
            "bash",
            "-s"
        ]

    log()
    log(f"> Running script in WSL distro: {DISTRO_NAME}")

    if user:
        log(f"> WSL user: {user}")

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    process.stdin.write(script.encode("utf-8"))
    process.stdin.close()

    for chunk in iter(process.stdout.readline, b""):
        text = chunk.decode("utf-8", errors="replace")
        print(text, end="", flush=True)
        write_log_file(text.rstrip("\n"))

    process.wait()

    if check and process.returncode != 0:
        raise RuntimeError(f"WSL script failed with exit code {process.returncode}")

    return process.returncode


def run_wsl_command(command, user=None, check=True):
    script = f"""
set -e
{command}
"""
    return run_wsl_script(script, user=user, check=check)


# ============================================================
# CHECK FUNCTIONS
# ============================================================

def is_wsl_feature_enabled():
    stdout, _, _ = capture_command(
        'powershell -Command "'
        'Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux '
        '| Select-Object -ExpandProperty State"'
    )

    return stdout.strip().lower() == "enabled"


def is_vm_platform_enabled():
    stdout, _, _ = capture_command(
        'powershell -Command "'
        'Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform '
        '| Select-Object -ExpandProperty State"'
    )

    return stdout.strip().lower() == "enabled"


def is_distro_installed():
    stdout, _, _ = capture_command("wsl -l -q")

    distros = []

    for line in stdout.splitlines():
        clean_line = line.replace("\x00", "").strip()

        if clean_line:
            distros.append(clean_line)

    return DISTRO_NAME in distros


def is_python_installed():
    if not is_distro_installed():
        return False

    command = f'test -x "{PYTHON_BIN}"'
    code = run_wsl_command(command, check=False)

    return code == 0


def is_mariadb_installed():
    if not is_distro_installed():
        return False

    script = """
dpkg -s mariadb-server > /dev/null 2>&1
"""

    code = run_wsl_script(script, user="root", check=False)

    return code == 0


def is_project_ready():
    if not is_distro_installed():
        return False

    script = f"""
test -d "$HOME/{PROJECT_FOLDER}"
test -d "$HOME/{PROJECT_FOLDER}/.git"
test -f "$HOME/{PROJECT_FOLDER}/{APP_PROGRAM_DIR}/app.py"
test -f "$HOME/{PROJECT_FOLDER}/{APP_PROGRAM_DIR}/requirements.txt"
test -f "$HOME/{PROJECT_FOLDER}/{AI_PROGRAM_DIR}/app.py"
test -f "$HOME/{PROJECT_FOLDER}/{AI_PROGRAM_DIR}/requirements.txt"
test -x "$HOME/{PROJECT_FOLDER}/{VENV_NAME}/bin/python"
test -x "$HOME/{PROJECT_FOLDER}/{VENV_NAME}/bin/gunicorn"
test -f "$HOME/{PROJECT_FOLDER}/.env"
"""

    code = run_wsl_script(script, check=False)

    return code == 0


def show_status():
    require_windows()

    log("========== STATUS ==========")
    log(f"WSL feature enabled: {is_wsl_feature_enabled()}")
    log(f"Virtual Machine Platform enabled: {is_vm_platform_enabled()}")
    log(f"{DISTRO_NAME} installed: {is_distro_installed()}")

    if is_distro_installed():
        log(f"Python {PYTHON_VERSION} installed: {is_python_installed()}")
        log(f"MariaDB installed: {is_mariadb_installed()}")
        log(f"Project ready: {is_project_ready()}")

        run_wsl_command(
            f"""
echo
echo "Ubuntu version:"
lsb_release -a || cat /etc/os-release

echo
echo "MariaDB status:"
service mariadb status || service mysql status || true

echo
echo "MariaDB detected port:"
if [ -f "{MARIADB_PORT_FILE}" ]; then
    cat "{MARIADB_PORT_FILE}"
else
    echo "Port file not found. Run install or run first."
fi

echo
echo "Project folder:"
if [ -d "$HOME/{PROJECT_FOLDER}" ]; then
    echo "$HOME/{PROJECT_FOLDER}"
else
    echo "Not found"
fi

echo
echo "Project .env:"
if [ -f "$HOME/{PROJECT_FOLDER}/.env" ]; then
    grep -E "^(MARIADB_HOST|MARIADB_PORT|DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD)=" "$HOME/{PROJECT_FOLDER}/.env" || true
else
    echo ".env not found"
fi
""",
            check=False
        )

    log("============================")


# ============================================================
# INSTALLATION
# ============================================================

def enable_wsl_features():
    log("Checking WSL features...")

    if not is_wsl_feature_enabled():
        log("WSL feature is not enabled. Enabling...")
        run_command(
            "dism.exe /online /enable-feature "
            "/featurename:Microsoft-Windows-Subsystem-Linux /all /norestart"
        )
    else:
        log("WSL feature is already enabled.")

    if not is_vm_platform_enabled():
        log("Virtual Machine Platform is not enabled. Enabling...")
        run_command(
            "dism.exe /online /enable-feature "
            "/featurename:VirtualMachinePlatform /all /norestart"
        )
    else:
        log("Virtual Machine Platform is already enabled.")

    log("WSL feature check finished.")


def install_ubuntu():
    if is_distro_installed():
        log(f"{DISTRO_NAME} is already installed.")
        return

    log(f"Installing {DISTRO_NAME}...")
    log("If Ubuntu asks for a Linux username/password, complete it in the terminal.")
    log("If Windows asks for restart, restart your PC and run this script again.")

    run_command(f"wsl --install -d {DISTRO_NAME}")


def install_python_31213():
    log(f"Installing Python {PYTHON_VERSION} in resumable mode...")

    script = f"""
set -e

export DEBIAN_FRONTEND=noninteractive

echo "Checking existing Python binary..."

apt-get update

apt-get install -y \\
    build-essential \\
    wget \\
    curl \\
    git \\
    make \\
    libssl-dev \\
    zlib1g-dev \\
    libbz2-dev \\
    libreadline-dev \\
    libsqlite3-dev \\
    libffi-dev \\
    liblzma-dev \\
    tk-dev \\
    uuid-dev \\
    xz-utils

if [ -x "{PYTHON_BIN}" ]; then
    echo "Python {PYTHON_VERSION} already installed."
    "{PYTHON_BIN}" --version
    exit 0
fi

echo "Python {PYTHON_VERSION} not found. Installing..."

cd /tmp

if [ ! -f "Python-{PYTHON_VERSION}.tgz" ]; then
    echo "Downloading Python source..."
    wget --progress=bar:force:noscroll "https://www.python.org/ftp/python/{PYTHON_VERSION}/Python-{PYTHON_VERSION}.tgz"
else
    echo "Python source archive already exists."
fi

if [ ! -d "Python-{PYTHON_VERSION}" ]; then
    echo "Extracting Python source..."
    tar -xzf "Python-{PYTHON_VERSION}.tgz"
else
    echo "Python source folder already exists."
fi

cd "Python-{PYTHON_VERSION}"

if [ ! -f "Makefile" ]; then
    echo "Configuring Python build..."
    ./configure --prefix="{PYTHON_PREFIX}" --enable-optimizations --with-ensurepip=install
else
    echo "Python build already configured."
fi

echo "Building Python..."
make -j"$(nproc)"

echo "Installing Python..."
make altinstall

"{PYTHON_BIN}" -m pip install --progress-bar on --upgrade pip setuptools wheel

echo "Python installation complete."
"{PYTHON_BIN}" --version
"""

    run_wsl_script(script, user="root")


def install_and_start_mariadb():
    log("Installing and starting MariaDB...")

    script = f"""
set -e

export DEBIAN_FRONTEND=noninteractive

apt-get update

apt-get install -y \\
    mariadb-server \\
    mariadb-client \\
    iproute2

echo "Starting MariaDB service..."

service mariadb start || service mysql start || true

sleep 2

echo "Checking MariaDB connection..."

if ! mariadb -e "SELECT VERSION();" > /dev/null 2>&1; then
    echo "MariaDB service did not respond yet. Trying one more start..."
    service mariadb restart || service mysql restart || true
    sleep 3
fi

if ! mariadb -e "SELECT VERSION();" > /dev/null 2>&1; then
    echo "ERROR: MariaDB is installed but not responding."
    exit 1
fi

PORT="$(mariadb -N -B -e "SHOW VARIABLES LIKE 'port';" 2>/dev/null | awk '{{print $2}}' || true)"

if [ -z "$PORT" ]; then
    PORT="$(ss -ltn | awk '{{print $4}}' | awk -F: '/:3306$/ {{print $NF; exit}}' || true)"
fi

if [ -z "$PORT" ]; then
    PORT="3306"
fi

echo "$PORT" > "{MARIADB_PORT_FILE}"

echo "Preparing application database..."
mariadb <<SQL
CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '{DB_USER}'@'127.0.0.1' IDENTIFIED BY '{DB_PASSWORD}';
CREATE USER IF NOT EXISTS '{DB_USER}'@'localhost' IDENTIFIED BY '{DB_PASSWORD}';
ALTER USER '{DB_USER}'@'127.0.0.1' IDENTIFIED BY '{DB_PASSWORD}';
ALTER USER '{DB_USER}'@'localhost' IDENTIFIED BY '{DB_PASSWORD}';
GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'127.0.0.1';
GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

echo "MariaDB is running."
echo "MariaDB port: $PORT"
echo "Database: {DB_NAME}"
"""

    run_wsl_script(script, user="root")


def setup_project(clean_project=False):
    if "your-username/your-repo.git" in GIT_REPO_URL:
        raise RuntimeError(
            "GIT_REPO_URL is still the placeholder value. "
            "Edit GIT_REPO_URL in henokh_project.py before running install."
        )

    clean_value = "1" if clean_project else "0"

    log("Setting up project in resumable mode...")

    script = f"""
set -e

PROJECT_FOLDER="{PROJECT_FOLDER}"
APP_PROGRAM_DIR="{APP_PROGRAM_DIR}"
AI_PROGRAM_DIR="{AI_PROGRAM_DIR}"
GIT_REPO_URL="{GIT_REPO_URL}"
AUTO_GIT_PULL="{1 if AUTO_GIT_PULL else 0}"
MOBILEFACENET_REPO_URL="{MOBILEFACENET_REPO_URL}"
PYTHON_BIN="{PYTHON_BIN}"
VENV_NAME="{VENV_NAME}"
CLEAN_PROJECT="{clean_value}"
MARIADB_PORT_FILE="{MARIADB_PORT_FILE}"

cd "$HOME"

echo "Current Linux user: $(whoami)"
echo "Home directory: $HOME"

if [ "$CLEAN_PROJECT" = "1" ]; then
    echo "Clean project mode enabled."

    if [ -d "$PROJECT_FOLDER" ]; then
        BACKUP_NAME="${{PROJECT_FOLDER}}_backup_$(date +%Y%m%d_%H%M%S)"
        echo "Moving existing project to backup: $BACKUP_NAME"
        mv "$PROJECT_FOLDER" "$BACKUP_NAME"
    fi
fi

if [ -d "$PROJECT_FOLDER" ]; then
    echo "Project folder exists."

    if [ -d "$PROJECT_FOLDER/.git" ]; then
        echo "Valid Git repository found."
        cd "$PROJECT_FOLDER"

        if [ "$AUTO_GIT_PULL" = "1" ]; then
            echo "Saving local changes temporarily..."
            git stash push -u -m "auto-stash-before-installer-pull" || true

            echo "Pulling latest changes..."
            git pull || true
        else
            echo "Auto git pull disabled. Using current project files."
        fi
    else
        echo "Project folder exists but is not a Git repository."
        BACKUP_NAME="${{PROJECT_FOLDER}}_backup_$(date +%Y%m%d_%H%M%S)"
        echo "Moving broken folder to: $BACKUP_NAME"

        mv "$PROJECT_FOLDER" "$BACKUP_NAME"

        echo "Cloning repository..."
        git clone "$GIT_REPO_URL" "$PROJECT_FOLDER"

        cd "$PROJECT_FOLDER"
    fi
else
    echo "Project folder does not exist."
    echo "Cloning repository..."

    git clone "$GIT_REPO_URL" "$PROJECT_FOLDER"

    cd "$PROJECT_FOLDER"
fi

echo "Checking Python..."
if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: Python binary not found: $PYTHON_BIN"
    exit 1
fi

"$PYTHON_BIN" --version
VENV_PYTHON="$PWD/$VENV_NAME/bin/python"
VENV_PIP="$PWD/$VENV_NAME/bin/pip"

echo "Checking virtual environment..."
if [ ! -x "$VENV_NAME/bin/python" ]; then
    echo "Creating virtual environment..."
    "$PYTHON_BIN" -m venv "$VENV_NAME"
else
    echo "Virtual environment already exists."
fi

echo "Upgrading pip..."
"$VENV_PYTHON" -m pip install --progress-bar on --upgrade pip setuptools wheel

if [ -f "$APP_PROGRAM_DIR/requirements.txt" ]; then
    echo "Installing/updating backend requirements..."
    "$VENV_PIP" install --progress-bar on -r "$APP_PROGRAM_DIR/requirements.txt"
else
    echo "ERROR: $APP_PROGRAM_DIR/requirements.txt not found."
    exit 1
fi

if [ -f "$AI_PROGRAM_DIR/requirements.txt" ]; then
    echo "Installing/updating AI service requirements..."
    "$VENV_PIP" install --progress-bar on -r "$AI_PROGRAM_DIR/requirements.txt"
else
    echo "ERROR: $AI_PROGRAM_DIR/requirements.txt not found."
    exit 1
fi

echo "Repairing typing_extensions if needed..."
"$VENV_PIP" install --progress-bar on --force-reinstall "typing_extensions>=4.15.0"

echo "Repairing CPU Torch stack if needed..."
"$VENV_PIP" install --progress-bar on --force-reinstall --index-url https://download.pytorch.org/whl/cpu "torch==2.5.1+cpu" "torchvision==0.20.1+cpu"

echo "Repairing TensorFlow/Keras if needed..."
"$VENV_PIP" install --progress-bar on --force-reinstall "tensorflow==2.21.0" "keras>=3.12.0"

echo "Checking Gunicorn..."
if ! "$VENV_PYTHON" -m pip show gunicorn > /dev/null 2>&1; then
    echo "Installing Gunicorn..."
    "$VENV_PIP" install --progress-bar on gunicorn
else
    echo "Gunicorn already installed."
fi

echo "Saving MariaDB environment values..."

if [ -f "$MARIADB_PORT_FILE" ]; then
    MARIADB_PORT="$(cat "$MARIADB_PORT_FILE")"
else
    MARIADB_PORT="3306"
fi

ENV_FILE=".env"

touch "$ENV_FILE"

set_env_value() {{
    KEY="$1"
    VALUE="$2"

    if grep -q "^${{KEY}}=" "$ENV_FILE"; then
        sed -i "s|^${{KEY}}=.*|${{KEY}}=${{VALUE}}|" "$ENV_FILE"
    else
        echo "${{KEY}}=${{VALUE}}" >> "$ENV_FILE"
    fi
}}

set_env_value "MARIADB_HOST" "127.0.0.1"
set_env_value "MARIADB_PORT" "$MARIADB_PORT"
set_env_value "DB_HOST" "127.0.0.1"
set_env_value "DB_PORT" "$MARIADB_PORT"
set_env_value "DB_NAME" "{DB_NAME}"
set_env_value "DB_USER" "{DB_USER}"
set_env_value "DB_PASSWORD" "{DB_PASSWORD}"
set_env_value "AI_SERVICE_URL" "http://{AI_SERVICE_HOST}:{AI_SERVICE_PORT}"
set_env_value "MOBILEFACENET_MODEL_PATH" "$PWD/$AI_PROGRAM_DIR/model/MobileFaceNet/pretrained_model/mobilefacenet_scripted.pt"

echo ".env database values:"
grep -E "^(MARIADB_HOST|MARIADB_PORT|DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD|AI_SERVICE_URL|MOBILEFACENET_MODEL_PATH)=" "$ENV_FILE" || true

echo "Loading .env..."
set -a
. "$ENV_FILE"
set +a

echo "Checking MobileFaceNet model..."
if [ -f "$MOBILEFACENET_MODEL_PATH" ]; then
    echo "MobileFaceNet model found: $MOBILEFACENET_MODEL_PATH"
else
    echo "Cloning foamliu/MobileFaceNet..."
    mkdir -p "$AI_PROGRAM_DIR/model"

    if [ -d "$AI_PROGRAM_DIR/model/MobileFaceNet" ]; then
        BACKUP_NAME="$AI_PROGRAM_DIR/model/MobileFaceNet_backup_$(date +%Y%m%d_%H%M%S)"
        echo "Moving incomplete MobileFaceNet folder to: $BACKUP_NAME"
        mv "$AI_PROGRAM_DIR/model/MobileFaceNet" "$BACKUP_NAME"
    fi

    git clone "$MOBILEFACENET_REPO_URL" "$AI_PROGRAM_DIR/model/MobileFaceNet"
fi

echo "Running database migrations..."
(cd "$APP_PROGRAM_DIR" && "$VENV_PYTHON" -m flask --app app migrate-db)

echo "Seeding default admin user..."
(cd "$APP_PROGRAM_DIR" && "$VENV_PYTHON" -m flask --app app seed-admin)

echo "Project setup complete."
"""

    run_wsl_script(script)


def install_all(clean_project=False):
    require_windows()
    require_admin()

    enable_wsl_features()
    install_ubuntu()

    if not is_distro_installed():
        raise RuntimeError(
            f"{DISTRO_NAME} is still not installed.\n"
            "If Windows requested a restart, restart your PC and run this command again:\n"
            "python henokh_project.py install"
        )

    install_python_31213()
    install_and_start_mariadb()
    setup_project(clean_project=clean_project)

    log()
    log("Installation / continuation finished successfully.")


# ============================================================
# RUN PROGRAM
# ============================================================

def start_mariadb_for_run():
    log("Starting MariaDB before running Flask app...")

    script = f"""
set -e

if ! dpkg -s mariadb-server > /dev/null 2>&1; then
    echo "ERROR: MariaDB is not installed."
    echo "Please run: python henokh_project.py install"
    exit 1
fi

service mariadb start || service mysql start || true

sleep 2

if ! mariadb -e "SELECT VERSION();" > /dev/null 2>&1; then
    service mariadb restart || service mysql restart || true
    sleep 3
fi

if ! mariadb -e "SELECT VERSION();" > /dev/null 2>&1; then
    echo "ERROR: MariaDB is not responding."
    exit 1
fi

PORT="$(mariadb -N -B -e "SHOW VARIABLES LIKE 'port';" 2>/dev/null | awk '{{print $2}}' || true)"

if [ -z "$PORT" ]; then
    PORT="$(ss -ltn | awk '{{print $4}}' | awk -F: '/:3306$/ {{print $NF; exit}}' || true)"
fi

if [ -z "$PORT" ]; then
    PORT="3306"
fi

echo "$PORT" > "{MARIADB_PORT_FILE}"

echo "Preparing application database..."
mariadb <<SQL
CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '{DB_USER}'@'127.0.0.1' IDENTIFIED BY '{DB_PASSWORD}';
CREATE USER IF NOT EXISTS '{DB_USER}'@'localhost' IDENTIFIED BY '{DB_PASSWORD}';
ALTER USER '{DB_USER}'@'127.0.0.1' IDENTIFIED BY '{DB_PASSWORD}';
ALTER USER '{DB_USER}'@'localhost' IDENTIFIED BY '{DB_PASSWORD}';
GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'127.0.0.1';
GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

echo "MariaDB running on port: $PORT"
echo "Database: {DB_NAME}"
"""

    run_wsl_script(script, user="root")


def pull_project():
    require_windows()

    if not is_distro_installed():
        raise RuntimeError(
            f"{DISTRO_NAME} is not installed.\n"
            "Run this first:\n"
            "python henokh_project.py install"
        )

    if not is_project_ready():
        raise RuntimeError(
            "Project prerequisites are missing.\n"
            "Run this first:\n"
            "python henokh_project.py install"
        )

    start_mariadb_for_run()

    log("Pulling latest project version and updating dependencies...")

    script = f"""
set -e

cd "$HOME/{PROJECT_FOLDER}"

echo "Current folder: $(pwd)"
APP_PROGRAM_DIR="{APP_PROGRAM_DIR}"
AI_PROGRAM_DIR="{AI_PROGRAM_DIR}"
VENV_PYTHON="$PWD/{VENV_NAME}/bin/python"
VENV_PIP="$PWD/{VENV_NAME}/bin/pip"

if [ ! -d ".git" ]; then
    echo "ERROR: This folder is not a Git repository."
    exit 1
fi

if [ -f "{MARIADB_PORT_FILE}" ]; then
    MARIADB_PORT="$(cat "{MARIADB_PORT_FILE}")"
else
    MARIADB_PORT="3306"
fi

ENV_FILE=".env"
touch "$ENV_FILE"

set_env_value() {{
    KEY="$1"
    VALUE="$2"

    if grep -q "^${{KEY}}=" "$ENV_FILE"; then
        sed -i "s|^${{KEY}}=.*|${{KEY}}=${{VALUE}}|" "$ENV_FILE"
    else
        echo "${{KEY}}=${{VALUE}}" >> "$ENV_FILE"
    fi
}}

set_env_value "MARIADB_HOST" "127.0.0.1"
set_env_value "MARIADB_PORT" "$MARIADB_PORT"
set_env_value "DB_HOST" "127.0.0.1"
set_env_value "DB_PORT" "$MARIADB_PORT"
set_env_value "DB_NAME" "{DB_NAME}"
set_env_value "DB_USER" "{DB_USER}"
set_env_value "DB_PASSWORD" "{DB_PASSWORD}"
set_env_value "AI_SERVICE_URL" "http://{AI_SERVICE_HOST}:{AI_SERVICE_PORT}"
set_env_value "MOBILEFACENET_MODEL_PATH" "$PWD/$AI_PROGRAM_DIR/model/MobileFaceNet/pretrained_model/mobilefacenet_scripted.pt"

echo "Saving local changes temporarily..."
git stash push -u -m "auto-stash-before-manual-pull" || true

echo "Pulling latest changes..."
git pull

echo "Installing/updating backend requirements..."
"$VENV_PIP" install --progress-bar on -r "$APP_PROGRAM_DIR/requirements.txt"

echo "Installing/updating AI service requirements..."
"$VENV_PIP" install --progress-bar on -r "$AI_PROGRAM_DIR/requirements.txt"

echo "Repairing typing_extensions if needed..."
"$VENV_PIP" install --progress-bar on --force-reinstall "typing_extensions>=4.15.0"

echo "Repairing CPU Torch stack if needed..."
"$VENV_PIP" install --progress-bar on --force-reinstall --index-url https://download.pytorch.org/whl/cpu "torch==2.5.1+cpu" "torchvision==0.20.1+cpu"

echo "Repairing TensorFlow/Keras if needed..."
"$VENV_PIP" install --progress-bar on --force-reinstall "tensorflow==2.21.0" "keras>=3.12.0"

echo "Checking Gunicorn..."
if ! "$VENV_PYTHON" -m pip show gunicorn > /dev/null 2>&1; then
    "$VENV_PIP" install --progress-bar on gunicorn
fi

echo "Loading .env..."
set -a
. "$ENV_FILE"
set +a

echo "Checking MobileFaceNet model..."
if [ -f "$MOBILEFACENET_MODEL_PATH" ]; then
    echo "MobileFaceNet model found: $MOBILEFACENET_MODEL_PATH"
else
    echo "Cloning foamliu/MobileFaceNet..."
    mkdir -p "$AI_PROGRAM_DIR/model"

    if [ -d "$AI_PROGRAM_DIR/model/MobileFaceNet" ]; then
        BACKUP_NAME="$AI_PROGRAM_DIR/model/MobileFaceNet_backup_$(date +%Y%m%d_%H%M%S)"
        echo "Moving incomplete MobileFaceNet folder to: $BACKUP_NAME"
        mv "$AI_PROGRAM_DIR/model/MobileFaceNet" "$BACKUP_NAME"
    fi

    git clone "{MOBILEFACENET_REPO_URL}" "$AI_PROGRAM_DIR/model/MobileFaceNet"
fi

echo "Running database migrations..."
(cd "$APP_PROGRAM_DIR" && "$VENV_PYTHON" -m flask --app app migrate-db)
echo "Database migrations finished."

echo "Seeding default admin user..."
(cd "$APP_PROGRAM_DIR" && "$VENV_PYTHON" -m flask --app app seed-admin)
echo "Default admin user check finished."

echo "Project pull/update complete."
"""

    run_wsl_script(script)


def kill_app_port_for_run():
    log(f"Checking service ports {GUNICORN_PORT} and {AI_SERVICE_PORT} before starting program...")

    script = f"""
set -e

SERVICE_PORTS="{GUNICORN_PORT} {AI_SERVICE_PORT}"

for APP_PORT in $SERVICE_PORTS; do
echo "Checking for processes listening on port $APP_PORT..."

PIDS="$(ss -ltnp "sport = :$APP_PORT" 2>/dev/null | sed -n 's/.*pid=\\([0-9]\\+\\).*/\\1/p' | sort -u || true)"

if [ -z "$PIDS" ]; then
    echo "No process is using port $APP_PORT."
    continue
fi

echo "Stopping process(es) on port $APP_PORT: $PIDS"
ps -fp $PIDS || true
kill $PIDS 2>/dev/null || true
sleep 2

for PID in $PIDS; do
    if kill -0 "$PID" 2>/dev/null; then
        echo "Process $PID still running. Force stopping..."
        kill -9 "$PID" 2>/dev/null || true
    fi
done

REMAINING="$(ss -ltnp "sport = :$APP_PORT" 2>/dev/null | sed -n 's/.*pid=\\([0-9]\\+\\).*/\\1/p' | sort -u || true)"

if [ -n "$REMAINING" ]; then
    echo "ERROR: Port $APP_PORT is still used by process(es): $REMAINING"
    ps -fp $REMAINING || true
    exit 1
fi

echo "Port $APP_PORT is ready."
done
"""

    run_wsl_script(script, user="root")


def run_program():
    require_windows()

    if not is_distro_installed():
        raise RuntimeError(
            f"{DISTRO_NAME} is not installed.\n"
            "Run this first:\n"
            "python henokh_project.py install"
        )

    if not is_project_ready():
        raise RuntimeError(
            "Project prerequisites are missing.\n"
            "Run this first:\n"
            "python henokh_project.py install"
        )

    start_mariadb_for_run()
    kill_app_port_for_run()

    log("Starting project...")

    script = f"""
set -e

cd "$HOME/{PROJECT_FOLDER}"

echo "Current folder: $(pwd)"
APP_PROGRAM_DIR="{APP_PROGRAM_DIR}"
AI_PROGRAM_DIR="{AI_PROGRAM_DIR}"
VENV_PYTHON="$PWD/{VENV_NAME}/bin/python"
GUNICORN_BIN="$PWD/{VENV_NAME}/bin/gunicorn"

if [ ! -d ".git" ]; then
    echo "ERROR: This folder is not a Git repository."
    exit 1
fi

if [ -f "{MARIADB_PORT_FILE}" ]; then
    MARIADB_PORT="$(cat "{MARIADB_PORT_FILE}")"
else
    MARIADB_PORT="3306"
fi

ENV_FILE=".env"
touch "$ENV_FILE"

set_env_value() {{
    KEY="$1"
    VALUE="$2"

    if grep -q "^${{KEY}}=" "$ENV_FILE"; then
        sed -i "s|^${{KEY}}=.*|${{KEY}}=${{VALUE}}|" "$ENV_FILE"
    else
        echo "${{KEY}}=${{VALUE}}" >> "$ENV_FILE"
    fi
}}

set_env_value "MARIADB_HOST" "127.0.0.1"
set_env_value "MARIADB_PORT" "$MARIADB_PORT"
set_env_value "DB_HOST" "127.0.0.1"
set_env_value "DB_PORT" "$MARIADB_PORT"
set_env_value "DB_NAME" "{DB_NAME}"
set_env_value "DB_USER" "{DB_USER}"
set_env_value "DB_PASSWORD" "{DB_PASSWORD}"
set_env_value "AI_SERVICE_URL" "http://{AI_SERVICE_HOST}:{AI_SERVICE_PORT}"
set_env_value "MOBILEFACENET_MODEL_PATH" "$PWD/$AI_PROGRAM_DIR/model/MobileFaceNet/pretrained_model/mobilefacenet_scripted.pt"

echo "Database environment:"
grep -E "^(MARIADB_HOST|MARIADB_PORT|DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD|AI_SERVICE_URL|MOBILEFACENET_MODEL_PATH)=" "$ENV_FILE" || true

echo "Loading .env..."
set -a
. "$ENV_FILE"
set +a

echo "Running database migrations..."
(cd "$APP_PROGRAM_DIR" && "$VENV_PYTHON" -m flask --app app migrate-db)
echo "Database migrations finished."

echo
echo "========================================"
echo "Starting Henokh Presence services..."
echo "Backend app URL:"
echo "http://localhost:{GUNICORN_PORT}"
echo "AI service URL:"
echo "http://localhost:{AI_SERVICE_PORT}"
echo "========================================"
echo "MariaDB Host: $DB_HOST"
echo "MariaDB Port: $DB_PORT"
echo "Database Name: $DB_NAME"
echo

cleanup_services() {{
    if [ -n "${{AI_PID:-}}" ]; then
        kill "$AI_PID" 2>/dev/null || true
    fi
}}

trap cleanup_services EXIT INT TERM

echo "Starting AI service..."
(cd "$AI_PROGRAM_DIR" && "$GUNICORN_BIN" \\
    --workers "{AI_SERVICE_WORKERS}" \\
    --timeout "{GUNICORN_TIMEOUT}" \\
    --bind "{AI_SERVICE_HOST}:{AI_SERVICE_PORT}" \\
    "app:app") &
AI_PID="$!"

sleep 3

if ! kill -0 "$AI_PID" 2>/dev/null; then
    echo "ERROR: AI service failed to start."
    exit 1
fi

echo "Starting backend app..."
(cd "$APP_PROGRAM_DIR" && "$GUNICORN_BIN" \\
    --workers "{GUNICORN_WORKERS}" \\
    --timeout "{GUNICORN_TIMEOUT}" \\
    --bind "{GUNICORN_HOST}:{GUNICORN_PORT}" \\
    "app:app")
"""

    run_wsl_script(script)


def open_shell():
    require_windows()

    if not is_distro_installed():
        raise RuntimeError(f"{DISTRO_NAME} is not installed.")

    run_command(f"wsl -d {DISTRO_NAME}")


def open_project_shell():
    require_windows()

    if not is_distro_installed():
        raise RuntimeError(f"{DISTRO_NAME} is not installed.")

    command = f'wsl -d {DISTRO_NAME} -- bash -lc "cd $HOME/{PROJECT_FOLDER} && exec bash"'
    run_command(command)


# ============================================================
# MAIN CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Henokh WSL Ubuntu installer and Flask Gunicorn runner"
    )
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser(
        "install",
        help="Install or continue installation"
    )
    install_parser.add_argument(
        "--clean-project",
        action="store_true",
        help="Move existing project folder to backup and clone again"
    )

    subparsers.add_parser(
        "run",
        help="Start MariaDB and run Gunicorn without pulling or updating dependencies"
    )

    subparsers.add_parser(
        "pull",
        help="Pull latest project version, update dependencies, and run database updates"
    )

    subparsers.add_parser(
        "status",
        help="Check WSL, Ubuntu, Python, MariaDB, and project status"
    )

    subparsers.add_parser(
        "shell",
        help="Open Ubuntu WSL shell"
    )

    subparsers.add_parser(
        "project-shell",
        help="Open Ubuntu WSL shell inside project folder"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "install":
            install_all(clean_project=args.clean_project)
            if args.elevated:
                log()
                log("Install finished. You can close this Administrator window.")
                pause_before_exit()

        elif args.command == "run":
            run_program()

        elif args.command == "pull":
            pull_project()

        elif args.command == "status":
            show_status()

        elif args.command == "shell":
            open_shell()

        elif args.command == "project-shell":
            open_project_shell()

    except KeyboardInterrupt:
        log()
        log("Cancelled by user.")
        if args.elevated:
            pause_before_exit()
        sys.exit(1)

    except Exception as e:
        log()
        log("ERROR:")
        log(str(e))
        log()
        log(f"Log file: {LOG_FILE}")
        if args.elevated:
            pause_before_exit()
        sys.exit(1)


if __name__ == "__main__":
    main()
