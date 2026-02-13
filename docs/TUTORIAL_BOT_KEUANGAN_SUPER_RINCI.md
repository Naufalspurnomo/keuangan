# Tutorial Super Rinci Penggunaan Bot Keuangan

## Status Dokumen

- Tanggal validasi implementasi: 13 Februari 2026
- Basis akurasi: perilaku aktual kode bot (routing, command handler, pending flow, OCR flow, revision flow, dan query flow)
- Tujuan: mengurangi salah paham konteks agar user tim menggunakan format yang konsisten dan minim revisi

## 1) Ringkasan Cepat (Jika Hanya Baca 2 Menit)

- Selalu pakai pola: `[aksi] [keterangan] [nominal] [konteks] [opsional sumber dana]`
- Jika transaksi project, wajib ada kata `projek/project/proyek` + nama project
- Jika operasional kantor, wajib ada kata `kantor` atau `operasional`
- Untuk update saldo awal dompet, gunakan kata `update saldo` / `set saldo` + alias dompet + nominal target
- Jika bot sedang menunggu jawaban menu, balas sesuai angka/menu dalam waktu maksimal 15 menit
- Di grup, paling aman selalu reply pesan bot (jangan kirim angka lepas tanpa reply)

## 2) Cakupan Fitur yang Aktif di Versi Ini

### 2.1 Input yang didukung

- Teks transaksi
- Gambar struk/nota + caption (OCR)
- Gambar dulu lalu teks menyusul (selama sesi masih aktif)

### 2.2 Fitur transaksi inti

- Routing otomatis: `PROJECT` vs `OPERATIONAL` vs `TRANSFER/update saldo` vs `AMBIGUOUS`
- Pencatatan project ke 3 dompet utama
- Pencatatan operasional ke sheet `Operasional Kantor` (dengan tag sumber dompet)
- Pencatatan utang antar dompet (OPEN/PAID/CANCELLED)
- Pelunasan utang otomatis via teks natural atau command `/lunas`
- Update saldo dompet mode absolut (set saldo target)
- Revisi nominal / pindah scope / undo transaksi

### 2.3 Fitur laporan dan query

- `/status`, `/saldo`, `/list`, `/laporan`, `/laporan30`, `/link`
- `/exportpdf` bulanan atau rentang tanggal
- `/tanya ...` untuk query natural language berbasis data real transaksi

## 3) Entitas Dasar yang Harus Dipahami User

### 3.1 Dompet dan company

- `CV HB(101)` -> company: `HOLLA` dan `HOJJA`
- `TX SBY(216)` -> company: `TEXTURIN-Surabaya`
- `TX BALI(087)` -> company: `TEXTURIN-Bali`

### 3.2 Alias dompet yang dikenali (contoh umum)

- CV HB: `cv hb`, `101`, `holla`, `hojja`, `holja`
- TX SBY: `tx sby`, `216`, `texturin`, `surabaya`, `sby`
- TX BALI: `tx bali`, `087`, `87`, `bali`, `denpasar`

### 3.3 Prefix nama project untuk CV HB

Jika project masuk ke dompet `CV HB(101)`, bot akan menjaga prefix company agar project tidak campur, misalnya:

- `Holla - Villa Arta`
- `Hojja - Villa Arta`

## 4) Formula Penulisan Standar (Wajib Konsisten)

## 4.1 Formula inti

`[aksi] [keterangan] [nominal] [konteks] [opsional sumber dana]`

Contoh:

- `bayar tukang plafon 2jt projek Ruko Panjer`
- `bayar listrik 850rb operasional kantor`
- `update saldo dompet tx sby 10jt`
- `bayar cat 1.2jt projek Villa Arta utang dari TX SBY`

## 4.2 Format nominal yang aman

Bot dapat membaca banyak variasi nominal:

- `150000`
- `150.000`
- `150rb`
- `1.5jt`
- `2 juta`

Agar akurat, hindari format ambigu seperti angka campur simbol tidak standar.

## 4.3 Keyword konteks paling penting

- Project: `projek`, `project`, `proyek`, `prj`
- Operasional: `kantor`, `operasional`, `operational`, `ops`
- Update saldo: `update saldo`, `set saldo`, `isi dompet`, `samakan saldo`
- Utang antar dompet: `utang/hutang/minjam/pinjam` + alias dompet

## 5) Tutorial Per Fitur (Step-by-Step)

## 5.1 Fitur A: Catat Transaksi Project (Project Berjalan)

### Tujuan

Mencatat transaksi project yang sudah punya nama project jelas.

### Format direkomendasikan

`[aksi] [keterangan] [nominal] projek [NamaProject]`

### Contoh

- `beli cat 1.2jt projek Villa Arta`
- `bayar tukang 2jt projek Ruko Panjer`

### Alur bot

1. Bot baca nominal + konteks project
2. Bot resolve dompet/company berdasarkan context/history
3. Jika sudah yakin, transaksi disimpan
4. Jika perlu konfirmasi, bot tampilkan draft project dengan opsi:
   - `1 Simpan`
   - `2 Ganti dompet`
   - `3 Ubah projek`
   - `4 Batal`

### Catatan akurasi

- Nama project harus konsisten ejaannya
- Hindari nama project berupa kata generik (contoh: `gaji`, `operasional`, `umum`)

## 5.2 Fitur B: Project Baru

### Kondisi 1: Project baru dimulai dari pemasukan (DP)

Contoh:

- `terima dp 20jt projek Villa Arta`

Bot akan menandai lifecycle `(Start)` pada batch baru sesuai rule lifecycle.

### Kondisi 2: Project baru dimulai dari pengeluaran

Contoh:

- `bayar tukang 5jt projek Villa Arta`

Bot akan memberi konfirmasi khusus:

- `1 Lanjutkan sebagai project baru`
- `2 Ubah jadi Operasional Kantor`
- `3 Batal`

Tujuan konfirmasi ini agar user tidak salah memasukkan pengeluaran operasional sebagai project baru.

## 5.3 Fitur C: Operasional Kantor

### Format direkomendasikan

`[aksi] [keterangan] [nominal] operasional kantor`
atau
`[aksi] [keterangan] [nominal] kantor`

Contoh:

- `bayar listrik kantor 850rb`
- `beli atk kantor 150rb`

### Alur bot

1. Bot mendeteksi scope operasional
2. Bot meminta dompet sumber dana (karena operasional dipotong dari dompet tertentu)
3. Pilihan dompet:
   - `1 CV HB (101)`
   - `2 TX SBY (216)`
   - `3 TX BALI (087)`
   - `4 Ini ternyata Project` (switch mode)
4. Setelah dompet terpilih, bot simpan ke sheet `Operasional Kantor`

### Kategori operasional otomatis

Bot memetakan kategori dari keyword, contoh:

- `gaji` -> `Gaji`
- `listrik/pln/air/pdam/wifi/internet` -> `ListrikAir`
- `makan/minum/snack/konsumsi` -> `Konsumsi`
- `atk/peralatan` -> `Peralatan`
- selain itu -> `Lain Lain`

## 5.4 Fitur D: Update Saldo Dompet (Absolute Set)

### Kapan dipakai

Saat ingin menyamakan saldo dompet dengan angka aktual.

### Format direkomendasikan

- `update saldo dompet TX SBY 10jt`
- `set saldo dompet CV HB 25jt`
- `samakan saldo tx bali 7.5jt`

### Perilaku sistem

1. Bot membaca saldo target
2. Bot cek saldo real dompet saat ini
3. Bot menghitung selisih penyesuaian
4. Bot membuat 1 transaksi `Saldo Umum` (pemasukan atau pengeluaran sesuai delta)
5. Bot kirim catatan rumus penyesuaian + verifikasi saldo

### Catatan penting

Jika saldo saat ini sudah sama dengan target, bot tidak membuat transaksi baru.

## 5.5 Fitur E: Project Dengan Sumber Dana Utang Dompet Lain

### Format direkomendasikan

`[aksi] [keterangan] [nominal] projek [NamaProject] utang dari [alias dompet]`

Contoh:

- `bayar tukang 5jt projek Villa Arta utang dari TX SBY`

### Rule deteksi utang antar dompet

Dianggap utang antar dompet jika ada kombinasi:

- keyword `utang/hutang/minjam/pinjam`
- arah preposisi (`dari`, `dr`, `ke`, `kepada`, dll)
- alias dompet valid

### Hasil pencatatan

- Pengeluaran project tetap masuk dompet project
- Dompet pemberi pinjaman dicatat pengeluaran `Hutang ke dompet X` pada `Saldo Umum`
- Sheet `HUTANG` ditambah entry `OPEN`

## 5.6 Fitur F: Bayar Hutang Antar Dompet

### Cara 1: Natural language

- `bayar hutang ke TX SBY 2jt`
- `pelunasan hutang ke CV HB 5jt`
- `bayar hutang no 3`

### Cara 2: Command langsung

- `/lunas 3`

### Jika kandidat banyak

Bot akan tampilkan shortlist, lalu user balas angka 1..N untuk memilih hutang yang dilunasi.

### Konfirmasi

Untuk kandidat tunggal, bot tetap minta konfirmasi `Ya`/angka `1` agar aman.

## 5.7 Fitur G: OCR Struk / Nota

### Cara paling ideal

Kirim image + caption transaksi sekaligus.

Contoh caption:

- `struk beli cat 1.250.000 projek Vadim utang dari TX SBY`
- `struk bensin 205rb operasional kantor`

### Jika kirim terpisah

- Kirim image dulu
- Lalu kirim teks formula dalam sesi aktif (maksimal 15 menit)

### Konfirmasi nominal OCR

Pada mode ketat (non-fast), bot bisa meminta:

- balas `OK` jika nominal benar
- atau ketik nominal benar (contoh: `202500`)

### Best practice OCR

- Pastikan gambar jelas, tidak blur
- Hindari foto miring ekstrem
- Tetap beri caption konteks agar routing tidak salah

## 5.8 Fitur H: Revisi dan Pembatalan

## 5.8.1 Revisi nominal

Contoh:

- `/revisi 150rb`
- `/revisi fee 3rb`

## 5.8.2 Revisi scope

Contoh:

- `/revisi operational`
- `/revisi project Nama Project`

## 5.8.3 Undo transaksi

- `/undo`
- Bot akan minta konfirmasi hapus

## 5.8.4 Cancel sesi aktif

- `/cancel`
- Membatalkan flow pending yang sedang berjalan

### Aturan penting di grup

- Revisi di grup wajib reply ke pesan laporan bot
- Untuk menghindari salah target, selalu reply prompt/hasil bot terkait

## 5.9 Fitur I: Query Data (`/tanya`)

### Contoh pertanyaan yang direkomendasikan

- `/tanya cek keuangan hari ini`
- `/tanya total pengeluaran proyek villa arta 30 hari`
- `/tanya dompet tx sby pengeluaran minggu ini`
- `/tanya ranking projek paling untung bulan ini`
- `/tanya perbandingan dompet 30 hari`
- `/tanya hutang tx sby`

### Cakupan query engine

- Ringkasan umum pemasukan/pengeluaran/profit
- Query per project (termasuk detail/rincian transaksi)
- Query per dompet
- Query utang/piutang
- Ranking project/dompet
- Kategori biaya (gaji, material, operasional, dll)
- Min/Max transaksi (terbesar/terkecil)
- Perbandingan antar dompet

### Kata waktu yang dikenali

- `hari ini` -> 1 hari
- `kemarin` -> 2 hari terakhir
- `minggu ini` -> 7 hari
- `bulan ini` -> 30 hari
- `tahun ini` -> 365 hari
- `X hari/minggu/bulan/tahun`
- `sejak awal` / `alltime` / `total` -> sepanjang data

## 5.10 Fitur J: Laporan dan Monitoring

### `/status`

Ringkasan dashboard global: income, expense, balance, saldo per dompet, status hutang, dan status project.

### `/saldo`

Menampilkan saldo real tiap dompet dengan komponen:

- total masuk internal
- total keluar internal
- potongan operasional
- penyesuaian hutang OPEN
- saldo real akhir

### `/list`

Riwayat 7 hari terakhir (maks 15 baris).

### `/laporan` dan `/laporan30`

- `/laporan` -> ringkasan 7 hari
- `/laporan30` -> ringkasan 30 hari
- Termasuk statistik hutang antar dompet + snapshot saldo dompet

### `/link`

Mengirim link Google Sheets aktif.

## 5.11 Fitur K: Export PDF

### Format bulanan

- `/exportpdf 2026-01`
- `/exportpdf 01-2026`
- `/exportpdf Januari 2026`

### Format rentang tanggal

- `/exportpdf 2025-09-22 2025-10-22`
- `/exportpdf 22-09-2025 22-10-2025`

### Catatan

- Jika tanpa argumen, default periode bulan berjalan
- Jika data periode kosong, bot menolak generate PDF (by design agar tidak misleading)

## 6) Referensi Semua Command

| Command          | Fungsi                                       | Contoh                                | Catatan                                                 |
| ---------------- | -------------------------------------------- | ------------------------------------- | ------------------------------------------------------- |
| `/start`         | buka intro + ringkasan cara pakai            | `/start`                              | di private bisa juga alias teks (`start`, `mulai`, dll) |
| `/help`          | bantuan detail command + flow                | `/help`                               | di private bisa juga `help`/`bantuan`                   |
| `/status`        | dashboard ringkas global                     | `/status`                             | aman untuk cek cepat                                    |
| `/saldo`         | saldo real tiap dompet                       | `/saldo`                              | angka mempertimbangkan operasional + hutang OPEN        |
| `/list`          | list transaksi 7 hari                        | `/list`                               | max 15 item                                             |
| `/laporan`       | laporan 7 hari                               | `/laporan`                            | include statistik hutang                                |
| `/laporan30`     | laporan 30 hari                              | `/laporan30`                          | include statistik hutang                                |
| `/lunas <no>`    | lunasi hutang by nomor                       | `/lunas 3`                            | alternatif dari kalimat natural                         |
| `/link`          | link spreadsheet                             | `/link`                               | untuk akses sheet                                       |
| `/exportpdf ...` | export PDF laporan                           | `/exportpdf 2026-01`                  | terima bulanan/range                                    |
| `/tanya ...`     | query data natural language                  | `/tanya total pengeluaran minggu ini` | jawaban berbasis data real                              |
| `/revisi ...`    | revisi transaksi                             | `/revisi 150rb`                       | paling aman reply pesan bot                             |
| `/undo`          | hapus transaksi terakhir (dengan konfirmasi) | `/undo`                               | gunakan segera setelah transaksi salah                  |
| `/cancel`        | batalkan flow/sesi aktif                     | `/cancel`                             | jika tidak ada sesi aktif, bot tetap clear buffer       |
| `/catat ...`     | force bot memproses sebagai transaksi        | `/catat beli cat 500rb projek X`      | berguna di grup saat bot tidak tersapa                  |

## 7) Aturan Grup vs Private

## 7.1 Di private chat

- Alias non-slash banyak yang diterima (`status`, `saldo`, `laporan`, dll)
- Flow lebih longgar

## 7.2 Di grup

- Command harus format slash (`/status`, `/saldo`, dst)
- Bot akan mengabaikan chat santai/noise jika sinyal transaksi lemah
- Gunakan salah satu ini agar bot pasti proses:
  - mention bot
  - trigger `+catat ...`
  - command `/catat ...`
  - reply ke prompt bot yang sedang aktif

## 8) Troubleshooting (Kasus Umum)

### Kasus: Bot bilang tidak ada pertanyaan aktif

Penyebab:

- sesi pending sudah lewat TTL (15 menit)
- user balas angka tanpa reply prompt di grup yang ramai

Solusi:

- kirim ulang transaksi
- di grup, reply ke prompt bot terbaru

### Kasus: Nominal tidak terbaca

Solusi:

- kirim ulang dengan format jelas (`150rb`, `1.2jt`, `150000`)
- hindari campuran karakter non-angka

### Kasus: Salah pilih mode project/operasional

Solusi:

- gunakan `/revisi operational` atau `/revisi project NamaProject`
- jika masih pending, gunakan opsi switch mode dari menu

### Kasus: OCR tidak kebaca

Solusi:

- kirim foto lebih jelas
- tambahkan caption teks transaksi
- jika perlu, ketik ulang transaksi manual

### Kasus: PDF gagal

Cek:

- format periode benar
- periode punya data transaksi

## 9) Anti Salah Kaprah (Checklist Internal Tim)

- Jangan kirim pesan pendek seperti `catat ini` tanpa nominal/konteks
- Wajib konsisten penamaan project (hindari typo berganti-ganti)
- Untuk transaksi project, selalu tulis keyword `projek/project`
- Untuk operasional, selalu tulis `kantor/operasional`
- Untuk utang antar dompet, wajib sebut arah dompet (`dari`/`ke`)
- Saat bot bertanya, balas sesuai opsi (jangan lompat konteks)
- Gunakan `/cancel` jika flow sudah terlanjur salah sebelum disimpan

## 10) Template Siap Pakai (Copy-Paste)

### A. Project berjalan

`bayar [item] [nominal] projek [NamaProject]`

### B. Project baru (DP)

`terima dp [nominal] projek [NamaProject]`

### C. Operasional kantor

`bayar [item operasional] [nominal] operasional kantor`

### D. Update saldo dompet

`update saldo dompet [alias dompet] [nominal target]`

### E. Project dengan utang dompet lain

`bayar [item] [nominal] projek [NamaProject] utang dari [alias dompet]`

### F. Pelunasan hutang

`bayar hutang ke [alias dompet] [nominal]`
atau
`bayar hutang no [nomor]`

### G. Revisi nominal

`/revisi [nominal baru]`

## 11) Catatan Akurasi Implementasi

- TTL pending transaksi: 15 menit
- Default sistem menggunakan `FAST_MODE` (auto commit saat confidence cukup)
- Jika mode ketat diaktifkan, bot lebih sering meminta konfirmasi draft
- Voice note disebut di pesan start lama, tetapi implementasi parser aktif saat ini fokus pada teks + gambar/caption
- Perintah `/dompet` dan `/kategori` tidak dipakai sebagai command user utama di handler saat ini

## 12) Penutup

Dokumen ini disusun agar user operasional bisa mengikuti format yang sama, meminimalkan ambiguity, dan menurunkan risiko salah konteks saat pencatatan keuangan harian.
Jika ada rule bisnis baru (dompet baru, kategori baru, perubahan alur approval), dokumen ini wajib diperbarui bersamaan dengan update kode.
