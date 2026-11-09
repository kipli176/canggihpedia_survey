# Canggihpedia Survey

Canggihpedia Survey adalah aplikasi web internal untuk mengumpulkan dan merangkum hasil wawancara kebutuhan belajar digital. Aplikasi dirancang agar nyaman digunakan tutor melalui perangkat seluler, dengan penyimpanan lokal berbasis SQLite dan antarmuka administrasi yang sederhana.

## Fitur

- Formulir wawancara bertahap untuk beberapa kelompok responden
- Penyimpanan draf dan penyelesaian survei
- Hak akses tutor dan administrator
- Ringkasan hasil survei
- Ekspor data ke CSV
- Validasi input, perlindungan CSRF, dan password hashing
- Antarmuka responsif dan aksesibel
- Dukungan deployment menggunakan Docker Compose

## Teknologi

- Python 3.10+
- Flask
- SQLite
- Waitress
- Docker

## Struktur proyek

```text
.
├── app.py
├── data/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

Direktori `data/` digunakan untuk database runtime dan tidak disimpan dalam Git.

## Menjalankan secara lokal

Buat virtual environment dan instal dependensi:

```bash
python -m venv .venv
```

Linux atau macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Aplikasi tersedia di `http://127.0.0.1:8080`. Pada instalasi baru, buka `/setup` untuk membuat akun administrator pertama.

## Konfigurasi

Salin `.env.example` menjadi `.env`, lalu sesuaikan nilainya:

| Variabel | Keterangan |
| --- | --- |
| `APP_ENV` | Lingkungan aplikasi, misalnya `development` atau `production` |
| `SECRET_KEY` | Kunci acak untuk session dan CSRF |
| `DATABASE_PATH` | Lokasi file SQLite |
| `HOST` | Alamat bind server |
| `PORT` | Port aplikasi |
| `COOKIE_SECURE` | Gunakan `1` jika aplikasi dilayani melalui HTTPS |

Gunakan `SECRET_KEY` yang panjang dan acak untuk lingkungan produksi. Jangan menyimpan `.env` di repository.

## Docker Compose

Konfigurasi bawaan menggunakan network eksternal `cloudflared` dan menyimpan database pada `data/survey.sqlite3`.

```bash
docker network create cloudflared
docker compose up -d --build
```

Service dapat diakses dari network Docker melalui `http://survey:8080`. Status container dapat diperiksa dengan:

```bash
docker compose ps
docker compose logs -f survey
```

## Database

Database dibuat otomatis saat aplikasi pertama kali dijalankan. Skema aktif terdiri dari:

- `users` untuk akun dan hak akses
- `surveys` untuk data wawancara

Sebelum melakukan migrasi atau deployment besar, buat backup SQLite yang konsisten dan uji proses pemulihannya.

## Kontribusi

Kontribusi dari komunitas sangat diterima. Untuk mengirim perubahan:

1. Fork repository.
2. Buat branch dari branch utama.
3. Lakukan perubahan yang terfokus dan sertakan pengujian yang relevan.
4. Pastikan aplikasi dapat dikompilasi dan dijalankan.
5. Ajukan pull request dengan penjelasan masalah dan solusi.

Pemeriksaan minimum sebelum membuka pull request:

```bash
python -m py_compile app.py
```

Jangan menyertakan database, `.env`, kredensial, data responden, atau artefak runtime dalam commit.

## Pelaporan keamanan

Jangan membuka issue publik untuk laporan yang mengandung kredensial, data responden, atau detail kerentanan yang belum diperbaiki. Hubungi pengelola repository melalui kanal privat agar laporan dapat ditangani dengan aman.
