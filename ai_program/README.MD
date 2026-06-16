# `ai_program`

`ai_program` adalah service AI terpisah untuk pemrosesan wajah Henokh Presence.

Service ini menangani:

1. Face detection dengan YOLO.
2. Anti-spoof/liveness dengan `mini_cnn_real_spoof.keras`.
3. Crop wajah berdasarkan bounding box.
4. Embedding wajah dengan MobileFaceNet.

Endpoint utama:

| Endpoint | Method | Fungsi |
| --- | --- | --- |
| `/health` | `GET` | Mengecek service hidup. |
| `/analyze-frame` | `POST` | Menerima gambar base64, lalu mengembalikan detection, liveness, dan embedding jika diminta. |

Saat dijalankan lewat `python henokh_project.py run`, service ini berjalan dengan Gunicorn di:

```text
http://localhost:8001
```

Command manual dari folder project:

```bash
cd ai_program
gunicorn --workers 1 --bind 127.0.0.1:8001 app:app
```
