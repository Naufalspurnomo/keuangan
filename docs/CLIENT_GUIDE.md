# Panduan Pengguna Bot Keuangan

Dokumen ini ditujukan untuk user/klien agar input transaksi konsisten, akurat,
dan mudah dianalisis. Gunakan format sederhana tapi jelas.

## 1) Cara Pakai Paling Aman (Ringkas)

- Selalu tulis: nominal + keterangan + konteks (projek atau operasional).
- Jika projek, tulis kata "projek/project" + nama projek.
- Jika operasional kantor, tulis kata "kantor".
- Jika bot minta pilihan dompet/company, balas angka sesuai menu (batas 15 menit).
- Jika salah, reply pesan bot lalu gunakan /revisi atau /undo.

## 2) Contoh Pesan yang Ideal

Project:

```
DP 5jt projek Taman Indah
Pelunasan projek Taman Indah 20jt
Beli cat 350rb projek Taman Indah
```

Operasional kantor:

```
Bayar gaji staff kantor 2.500.000
Beli ATK kantor 150rb
Listrik kantor 1.250.000
```

Transfer saldo antar dompet:

```
Transfer 5jt dari CV HB ke TX SBY
Update saldo: isi dompet TX BALI 2jt dari CV HB
```

## 3) Dompet dan Company

Dompet yang tersedia:

- CV HB(101) -> menaungi HOLLA dan HOJJA
- TX SBY (216) -> Texturin Surabaya
- TX BALI (087) -> Texturin Bali

Mode Project (pilih company):

- 1 HOLLA
- 2 HOJJA
- 3 TEXTURIN-Surabaya
- 4 TEXTURIN-Bali

Mode Operasional (pilih dompet):

- 1 CV HB (101)
- 2 TX SBY (216)
- 3 TX BALI (087)

Jika salah mode:

- Dari Operasional ke Project: pilih "4. Ini ternyata Project"
- Dari Project ke Operasional: pilih "5. Ini ternyata Operasional Kantor"

Catatan CV HB:
Untuk dompet CV HB, nama projek otomatis diprefix HOLLA atau HOJJA agar tidak
campur. Contoh: "HOLLA - Taman Indah".

## 4) Foto Struk dan OCR

Agar OCR akurat, gunakan caption:

```
Struk bensin 205rb + fee 2.500
```

Jika bot menampilkan hasil OCR:

- Balas "OK" jika benar
- Atau ketik nominal yang benar (contoh: 207500)

Ini wajib jika nominal sensitif. OCR bisa salah baca angka.

## 5) Alur Singkat Bot

1. User kirim transaksi.
2. Bot analisis dan bertanya jika ada data yang kurang.
3. Bot minta pilihan dompet/company.
4. Bot tampilkan draft transaksi untuk konfirmasi.
5. Bot simpan ke spreadsheet dan kirim ringkasan.

Batas waktu jawaban menu adalah 15 menit. Jika lewat, kirim ulang transaksi.

## 6) Perintah yang Tersedia

Umum:

```
/start
/help
/status
/saldo
/list
/laporan
/laporan30
/link
```

Export PDF:

```
/exportpdf 2026-01
/exportpdf 2025-09-22 2025-10-22
```

Revisi:

```
/revisi 150rb
/revisi operational
/revisi project Nama Projek
/undo
```

Catatan /exportpdf:

- Format bulanan: YYYY-MM
- Format rentang: YYYY-MM-DD YYYY-MM-DD
- Jika tidak ada data, bot akan menolak agar hasil tetap akurat.

## 7) Revisi dan Pembatalan

Selalu reply pesan bot ketika revisi.

- Ubah nominal: /revisi 150rb
- Pindah ke operasional: /revisi operational
- Pindah ke project: /revisi project Nama Projek
- Hapus transaksi terakhir: /undo

Jika hanya mengetik "salah", bot akan kasih menu revisi.

## 8) Start dan Finish Projek

Bot akan menandai projek dengan label:

- (Start) jika projek baru pertama kali muncul
- (Finish) jika pemasukan mengandung kata:
  pelunasan, lunas, selesai, final payment

Contoh yang benar:

```
Pelunasan projek Taman Indah 20jt
```

Tips agar rapi:

- Gunakan "DP ..." untuk pemasukan awal (Start).
- Gunakan kata "pelunasan/lunas/selesai" untuk menutup (Finish).
- Jika transaksi pertama projek adalah pengeluaran, bot akan meminta konfirmasi.

## 9) Cara Pakai di Grup

Di grup, bot hanya merespon pesan yang jelas transaksi.
Cara memaksa bot:

- Mention bot: "@Bot catat ..."
- Atau gunakan trigger: "+catat ...", "/catat ..."
- Atau gunakan perintah /status, /saldo, dsb

Jika grup lagi chat santai, bot akan diam agar tidak spam.

## 10) Best Practice (Akurasi Maksimal)

- Hindari pesan "catat ini" tanpa detail.
- Selalu tulis nama projek yang konsisten.
- Hindari nama projek yang terlalu umum (contoh: "gaji", "beli cat").
- Jika ragu, tulis detail: "projek X", "operasional kantor", dan dompet.
