# `app_program`

`app_program` berisi frontend dan backend utama Henokh Presence:

1. Template HTML dan static asset.
2. Route Flask untuk login, dashboard, siswa, guru, kelas, settings, dan presensi.
3. Koneksi database, migrasi, dan model database.
4. Client HTTP untuk memanggil AI service di `ai_program`.

Backend tidak lagi memuat model YOLO, anti-spoof, atau MobileFaceNet secara langsung. Untuk proses wajah, backend mengirim gambar ke `AI_SERVICE_URL`, default:

```text
http://127.0.0.1:8001
```

Saat dijalankan lewat `python henokh_project.py run`, service ini berjalan dengan Gunicorn di:

```text
http://localhost:8000
```

Command manual dari folder project:

```bash
cd app_program
flask --app app migrate-db
flask --app app seed-admin
gunicorn --bind 0.0.0.0:8000 app:app
```
