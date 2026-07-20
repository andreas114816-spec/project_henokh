# Program augmentasi gambar

Program utama hanya memerlukan path folder sumber:

```bash
.venv/bin/python augmentation/augment_images.py
```

Program kemudian menampilkan `Masukkan path folder gambar:`. Path juga dapat
diberikan langsung sebagai argumen:

```bash
.venv/bin/python augmentation/augment_images.py /path/ke/folder_gambar
```

Hasil masuk langsung ke `augmented_images/` pada root project tanpa subfolder.
Setiap gambar sumber menghasilkan empat file `real` dan empat file `spoof`.
Versi `real` hanya diproses oleh `second_augmentation.py`, sedangkan versi
`spoof` diproses oleh `first_augmentation.py` lalu `second_augmentation.py`.

Nama sumber harus berbentuk `real_Name_NIM*.jpg` atau `spoof_Name_NIM*.jpg`.
Alternatifnya, gambar bernama `Name_NIM*.jpg` boleh diletakkan di dalam folder
`real/` atau `spoof/`. NIM wajib berupa angka. Contoh hasil:

```text
augmented_images/real_Budi Santoso_221234_aug1.jpg
augmented_images/real_Budi Santoso_221234_aug2.jpg
augmented_images/real_Budi Santoso_221234_aug3.jpg
augmented_images/real_Budi Santoso_221234_aug4.jpg
augmented_images/spoof_Budi Santoso_221234_aug1.jpg
augmented_images/spoof_Budi Santoso_221234_aug2.jpg
augmented_images/spoof_Budi Santoso_221234_aug3.jpg
augmented_images/spoof_Budi Santoso_221234_aug4.jpg
```

Folder hasil lain dapat dipilih bila dibutuhkan:

```bash
.venv/bin/python augmentation/augment_images.py /path/ke/folder_gambar --output /path/hasil
```

Dependency: `numpy`, `opencv-python`, dan `Pillow`.
