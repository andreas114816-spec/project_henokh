# Workflow Real-Life Henokh Presence System

File ini menjelaskan bagaimana sistem bekerja dalam kondisi operasional nyata.

## Jawaban singkat

- Mahasiswa tidak mendaftar sendiri. Pada implementasi saat ini, mahasiswa didaftarkan oleh admin/operator dari dashboard setelah login.
- Data wajah baru tidak menjadi data training untuk melatih ulang MobileFaceNet.
- Saat mahasiswa baru disimpan, sistem hanya membuat face embedding dari wajah yang tertangkap kamera, lalu menyimpan embedding itu di database.
- Saat presensi, sistem menjalankan inference: deteksi wajah, anti-spoof, buat embedding wajah live, lalu cocokkan dengan embedding mahasiswa yang sudah tersimpan.
- Jika mahasiswa diedit dan admin mengambil foto wajah baru, embedding lama akan diganti dengan embedding baru.

## Alur real-life

1. Admin login ke dashboard.
2. Admin menyiapkan master data: user, dosen/guru, kelas, jadwal kelas, waktu presensi, dan daftar mahasiswa di kelas.
3. Admin/operator membuka menu Student dan menambahkan mahasiswa.
4. Admin mengisi nama dan NIM, lalu menyalakan kamera untuk mengambil wajah mahasiswa.
5. Sistem memastikan hanya ada satu wajah. Jika anti-spoof aktif, wajah harus lolos pemeriksaan real-person.
6. Sistem memotong area wajah dan menjalankan MobileFaceNet untuk menghasilkan embedding.
7. Data mahasiswa dan embedding disimpan ke database.
8. Saat kelas berlangsung, operator membuka Presence Camera dan memilih kelas.
9. Kamera mengirim frame ke backend secara berkala.
10. Backend mendeteksi wajah, melakukan anti-spoof jika aktif, membuat embedding wajah live, dan membandingkan embedding itu dengan embedding mahasiswa di kelas terpilih.
11. Jika similarity melewati threshold, sistem mencatat attendance sebagai `presence` atau `late` sesuai aturan waktu kelas.
12. Jika waktu kelas sudah lewat, mahasiswa yang belum punya catatan attendance dapat ditandai `absen`.
13. Admin dapat membuka kalender/detail attendance untuk review dan koreksi manual.

## Diagram

File diagram ada di:

- `docs/workflows/henokh_real_life_workflow.svg`

Diagram SVG ini bisa dibuka langsung di browser atau dimasukkan ke dokumen/presentasi.
