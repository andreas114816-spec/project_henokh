# Panduan `henokh_project.py`

`henokh_project.py` adalah script bantu untuk menyiapkan dan menjalankan aplikasi Henokh Presence lewat Windows + Ubuntu WSL. Jadi, daripada setup WSL, Python, MariaDB, virtual environment, dependency, model MobileFaceNet, dan Gunicorn satu per satu, semua langkah pentingnya sudah dibungkus di script ini.

Singkatnya, script ini dipakai untuk:

1. Install kebutuhan aplikasi.
2. Menjalankan aplikasi.
3. Update project dari Git.
4. Cek status environment.
5. Masuk ke shell WSL atau folder project.

Script ini dijalankan dari Windows, bukan dari terminal Linux/WSL langsung. Nanti kalau ada pekerjaan yang harus dilakukan di Linux, script akan mengirim perintahnya ke Ubuntu WSL secara otomatis.

## Cara Pakai Cepat

Buka Command Prompt atau PowerShell di Windows, lalu masuk ke folder yang berisi `henokh_project.py`.

Command yang tersedia:

```powershell
python henokh_project.py install
python henokh_project.py run
python henokh_project.py pull
python henokh_project.py status
python henokh_project.py shell
python henokh_project.py project-shell
```

Alur paling umum biasanya seperti ini:

1. Jalankan `python henokh_project.py install` untuk setup pertama kali.
2. Setelah selesai, jalankan `python henokh_project.py run`.
3. Buka aplikasi di browser lewat `http://localhost:8000`.
4. Kalau ada update dari repository, jalankan `python henokh_project.py pull`.

## Konfigurasi Penting

Konfigurasi utama ada di bagian atas file `henokh_project.py`. Kalau ingin mengganti port, nama database, repo Git, atau versi Python, ubahnya dari sana.

| Konfigurasi | Kegunaan |
| --- | --- |
| `DISTRO_NAME` | Nama distro WSL yang dipakai. Saat ini `Ubuntu-22.04`. |
| `PROJECT_FOLDER` | Nama folder project di dalam home WSL. Saat ini `project_henokh`. |
| `GIT_REPO_URL` | URL repository Git project. |
| `AUTO_GIT_PULL` | Mengatur apakah command `install` boleh melakukan `git pull` otomatis saat folder project sudah ada. |
| `PYTHON_VERSION` | Versi Python yang akan dipakai. Saat ini `3.12.13`. |
| `VENV_NAME` | Nama virtual environment. Saat ini `.venv`. |
| `GUNICORN_APP` | Target aplikasi Gunicorn. Saat ini `app:app`. |
| `GUNICORN_HOST` | Host untuk Gunicorn. Saat ini `0.0.0.0`. |
| `GUNICORN_PORT` | Port aplikasi. Saat ini `8000`. |
| `GUNICORN_WORKERS` | Jumlah worker Gunicorn. Saat ini `3`. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Nama database, user, dan password MariaDB. |
| `MOBILEFACENET_REPO_URL` | Repository MobileFaceNet yang dipakai aplikasi. |
| `LOG_FILE` | Lokasi file log script. |

## Gambaran Cara Kerjanya

Script ini bertindak seperti jembatan antara Windows dan Ubuntu WSL.

Saat command dijalankan, script akan:

1. Mengecek dulu apakah script memang dijalankan dari Windows.
2. Meminta izin Administrator kalau command-nya butuh akses sistem, misalnya saat install.
3. Menjalankan command Windows seperti `wsl`, `dism.exe`, atau PowerShell.
4. Mengirim perintah Bash ke Ubuntu WSL untuk setup Linux, install dependency, update project, migrasi database, dan menjalankan aplikasi.
5. Menampilkan output di terminal sambil menyimpan log ke file.

Beberapa fungsi penting di dalam script:

| Fungsi | Fungsinya |
| --- | --- |
| `require_windows()` | Memastikan script dijalankan dari Windows. |
| `require_admin()` | Meminta akses Administrator saat dibutuhkan. |
| `run_command()` | Menjalankan command di Windows. |
| `run_wsl_script()` | Menjalankan script Bash di WSL. |
| `run_wsl_command()` | Menjalankan command singkat di WSL. |
| `write_log_file()` | Menyimpan output ke file log. |

## Command `install`

```powershell
python henokh_project.py install
```

Pakai command ini untuk instalasi pertama, atau untuk melanjutkan instalasi yang sebelumnya terhenti. Command ini membutuhkan akses Administrator di Windows.

Yang dilakukan oleh `install`:

1. Mengecek fitur WSL dan Virtual Machine Platform.
2. Mengaktifkan fitur WSL kalau belum aktif.
3. Menginstall Ubuntu WSL sesuai `DISTRO_NAME`.
4. Menginstall Python `3.12.13` ke `/opt/python-3.12.13`.
5. Menginstall dan menjalankan MariaDB.
6. Membuat database `presence`.
7. Membuat user database `user_admin`.
8. Menyiapkan folder project di `$HOME/project_henokh` dalam WSL.
9. Clone repository kalau folder project belum ada.
10. Kalau folder project sudah ada dan valid sebagai Git repository, script akan `git stash` lalu `git pull` jika `AUTO_GIT_PULL=True`.
11. Membuat virtual environment `.venv`.
12. Install dependency dari `requirements.txt`.
13. Memperbaiki dependency penting seperti `typing_extensions`, Torch CPU, TensorFlow, dan Keras.
14. Install Gunicorn kalau belum ada.
15. Membuat atau memperbarui file `.env`.
16. Mengecek model MobileFaceNet, lalu clone MobileFaceNet kalau belum ada.
17. Menjalankan migrasi database.
18. Membuat atau memastikan admin default lewat seed admin.

Kalau Windows meminta restart saat proses WSL, restart dulu komputernya. Setelah itu jalankan lagi:

```powershell
python henokh_project.py install
```

Tidak perlu khawatir kalau instalasi sempat berhenti di tengah. Script ini dibuat supaya bisa dilanjutkan lagi.

### Install Ulang Project

Kalau ingin clone ulang project dari awal:

```powershell
python henokh_project.py install --clean-project
```

Folder project lama tidak langsung dihapus. Script akan memindahkannya dulu menjadi backup, misalnya:

```text
project_henokh_backup_YYYYMMDD_HHMMSS
```

Setelah itu repository akan di-clone ulang.

## Command `run`

```powershell
python henokh_project.py run
```

Pakai command ini untuk menjalankan aplikasi setelah proses install selesai.

Yang dilakukan oleh `run`:

1. Mengecek apakah Ubuntu WSL sudah ada.
2. Mengecek apakah project sudah siap.
3. Menyalakan MariaDB.
4. Memastikan database dan user database tersedia.
5. Mengecek port aplikasi, yaitu `8000` secara default.
6. Kalau port sedang dipakai proses lain di WSL, proses itu akan dihentikan dulu.
7. Memperbarui nilai database di file `.env`.
8. Memuat `.env`.
9. Menjalankan aplikasi dengan Gunicorn.
10. Menampilkan alamat aplikasi.

Alamat default aplikasi:

```text
http://localhost:8000
```

Catatan: `run` hanya menjalankan aplikasi. Command ini tidak melakukan `git pull` dan tidak update dependency. Kalau ingin update project, gunakan `pull`.

## Command `pull`

```powershell
python henokh_project.py pull
```

Pakai command ini saat project perlu mengambil update terbaru dari repository.

Yang dilakukan oleh `pull`:

1. Mengecek apakah WSL dan project sudah siap.
2. Menyalakan MariaDB.
3. Masuk ke folder `$HOME/project_henokh`.
4. Memperbarui isi `.env`.
5. Menyimpan perubahan lokal sementara dengan:

```bash
git stash push -u -m "auto-stash-before-manual-pull"
```

6. Menjalankan `git pull`.
7. Install atau update dependency dari `requirements.txt`.
8. Memperbaiki dependency penting seperti `typing_extensions`, Torch CPU, TensorFlow, dan Keras.
9. Mengecek Gunicorn.
10. Mengecek model MobileFaceNet.
11. Menjalankan migrasi database.
12. Menjalankan seed admin.

Biasanya command ini dipakai setelah ada perubahan baru di GitHub atau repository utama.

## Command `status`

```powershell
python henokh_project.py status
```

Pakai command ini kalau ingin cek kondisi environment tanpa menjalankan aplikasi.

Yang dicek:

1. Fitur WSL.
2. Virtual Machine Platform.
3. Apakah `Ubuntu-22.04` sudah terinstall.
4. Apakah Python `3.12.13` sudah ada.
5. Apakah MariaDB sudah ada.
6. Apakah project sudah siap.
7. Versi Ubuntu.
8. Status service MariaDB.
9. Port MariaDB yang terdeteksi.
10. Lokasi folder project.
11. Konfigurasi database di `.env`.

## Command `shell`

```powershell
python henokh_project.py shell
```

Command ini membuka shell Ubuntu WSL sesuai `DISTRO_NAME`.

Pakai ini kalau ingin masuk ke environment Linux secara manual.

## Command `project-shell`

```powershell
python henokh_project.py project-shell
```

Command ini membuka shell WSL langsung di folder project:

```text
$HOME/project_henokh
```

Ini berguna kalau ingin menjalankan command manual seperti `git status`, mengecek `.env`, atau menjalankan command Flask langsung dari folder project.

## File `.env`

Script akan membuat atau memperbarui file `.env` di folder project WSL.

Contoh nilai yang disimpan:

```env
MARIADB_HOST=127.0.0.1
MARIADB_PORT=3306
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=presence
DB_USER=user_admin
DB_PASSWORD=password123
MOBILEFACENET_MODEL_PATH=/home/<user>/project_henokh/model/MobileFaceNet/pretrained_model/mobilefacenet_scripted.pt
```

Port MariaDB bisa saja berbeda. Script menyimpan port MariaDB yang berhasil terdeteksi di:

```text
/tmp/henokh_mariadb_port
```

## Menghubungkan MariaDB ke DBeaver

MariaDB yang dibuat oleh `henokh_project.py` juga bisa dibuka lewat DBeaver. Ini berguna kalau ingin melihat isi tabel, mengecek data absensi, atau menjalankan query SQL secara manual.

Sebelum membuka DBeaver, pastikan MariaDB di WSL sudah berjalan. Cara paling gampang adalah menjalankan aplikasi dulu:

```powershell
python henokh_project.py run
```

Atau kalau hanya ingin mengecek environment:

```powershell
python henokh_project.py status
```

Di DBeaver, buat koneksi baru seperti ini:

1. Buka DBeaver.
2. Klik `New Database Connection`.
3. Pilih `MariaDB`.
4. Isi konfigurasi koneksi.

Gunakan nilai berikut:

| Field DBeaver | Nilai |
| --- | --- |
| `Server Host` | `127.0.0.1` |
| `Port` | `3306` |
| `Database` | `presence` |
| `Username` | `user_admin` |
| `Password` | `password123` |

Kalau port MariaDB di komputer berbeda, pakai nilai dari `.env`:

```env
MARIADB_PORT=3306
DB_PORT=3306
```

Setelah semua terisi:

1. Klik `Test Connection`.
2. Kalau DBeaver meminta download driver MariaDB, izinkan download driver.
3. Kalau test berhasil, klik `Finish`.

Setelah konek, database yang dipakai aplikasi adalah:

```text
presence
```

Jadi tabel-tabel aplikasi bisa dilihat dari database tersebut.

### Kalau DBeaver Gagal Konek

Beberapa hal yang bisa dicek:

1. Pastikan `python henokh_project.py run` sedang berjalan, atau MariaDB sudah pernah dinyalakan oleh command `install`, `run`, atau `pull`.
2. Jalankan `python henokh_project.py status` untuk melihat port MariaDB yang terdeteksi.
3. Pastikan host di DBeaver memakai `127.0.0.1`, bukan nama distro WSL.
4. Pastikan username dan password sesuai dengan konfigurasi script:

```text
Username: user_admin
Password: password123
Database: presence
```

Kalau password atau nama database diubah di `henokh_project.py`, nilai di DBeaver juga harus ikut diubah.

## Log

Output script akan tampil di terminal dan juga disimpan ke file log.

Lokasinya diatur oleh kode ini:

```python
LOG_FILE = os.path.join(os.environ.get("TEMP", os.getcwd()), "henokh_project.log")
```

Di Windows, biasanya file log ada di:

```text
%TEMP%\henokh_project.log
```

Kalau terjadi error, script akan menampilkan lokasi file log tersebut.

## Troubleshooting

### Script Dijalankan dari WSL atau Linux

Script ini memang harus dijalankan dari Windows. Kalau muncul error karena script dijalankan dari WSL/Linux, buka PowerShell atau Command Prompt Windows lalu jalankan lagi:

```powershell
python henokh_project.py install
```

### Instalasi Berhenti karena Windows Minta Restart

Kalau Windows meminta restart saat mengaktifkan WSL, restart komputer dulu. Setelah menyala lagi, jalankan:

```powershell
python henokh_project.py install
```

### Project Belum Siap Saat `run`

Kalau `run` mengatakan project belum siap, biasanya instalasi belum lengkap. Jalankan:

```powershell
python henokh_project.py install
```

### Port 8000 Sudah Dipakai

Saat `run`, script akan mengecek port `8000`. Kalau ada proses lain di WSL yang memakai port itu, script akan mencoba menghentikannya dulu.

Kalau masih bermasalah, cek kondisi environment dengan:

```powershell
python henokh_project.py status
```

### Perlu Update dari Git

Gunakan:

```powershell
python henokh_project.py pull
```

Command ini akan menyimpan perubahan lokal sementara, mengambil update dari Git, update dependency, menjalankan migrasi database, dan seed admin.

### Ingin Masuk ke Folder Project di WSL

Gunakan:

```powershell
python henokh_project.py project-shell
```

Setelah masuk ke shell WSL, beberapa command manual yang sering dipakai:

```bash
git status
source .venv/bin/activate
flask --app app migrate-db
```

## Ringkasan Command

| Command | Dipakai Untuk | Yang Dilakukan |
| --- | --- | --- |
| `install` | Setup pertama atau memperbaiki instalasi | Setup WSL, Python, MariaDB, project, dependency, `.env`, migrasi, dan seed admin |
| `install --clean-project` | Clone ulang project | Backup folder project lama lalu clone ulang |
| `run` | Menjalankan aplikasi | Start MariaDB, kosongkan port aplikasi, lalu jalankan Gunicorn |
| `pull` | Mengambil update terbaru | `git stash`, `git pull`, update dependency, migrasi, dan seed admin |
| `status` | Mengecek environment | Menampilkan status WSL, Python, MariaDB, project, dan `.env` |
| `shell` | Masuk ke Ubuntu WSL | Membuka shell distro WSL |
| `project-shell` | Masuk langsung ke folder project | Membuka shell di `$HOME/project_henokh` |

## Catatan Pengembangan

Kalau ada konfigurasi yang diubah, sesuaikan command yang dijalankan setelahnya.

Contoh:

1. Kalau mengubah `GUNICORN_PORT`, jalankan lagi `python henokh_project.py run`.
2. Kalau mengubah `requirements.txt`, jalankan `python henokh_project.py pull` atau `python henokh_project.py install`.
3. Kalau mengubah struktur database, pastikan migrasi tetap bisa dijalankan lewat `flask --app app migrate-db`.
