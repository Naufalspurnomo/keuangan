# Allowlist Pengguna

Bot ini mendukung allowlist berbasis env var untuk membatasi siapa yang bisa mengirim pesan.

## Konfigurasi

Gunakan env var `ALLOWED_SENDER_IDS` dengan format daftar dipisahkan koma atau baris baru.
Jika kosong/tidak diisi, semua pengirim diizinkan.

### Format yang Didukung

Masukkan salah satu dari:
- Nomor WhatsApp (mis. `6281234567890` atau `+6281234567890`)
- Telegram `chat_id` atau `user_id` (angka)
- Username Telegram (dengan atau tanpa `@`)

### Contoh

```
ALLOWED_SENDER_IDS=6281234567890,+6289876543210,123456789,@username
```

Atau dengan baris baru:

```
ALLOWED_SENDER_IDS=6281234567890
123456789
@username
```
