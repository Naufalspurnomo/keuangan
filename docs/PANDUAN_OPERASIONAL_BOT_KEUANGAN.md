# Buku Panduan Operasional Bot Keuangan

Versi dokumen: 3 Agustus 2026
Status: panduan operasional berdasarkan perilaku source code bot saat ini
Audiens: admin keuangan, admin pengganti, owner, dan operator teknis

## Tujuan buku ini

Bot Keuangan adalah asisten pencatatan melalui WhatsApp dan Telegram. Bot membaca teks transaksi atau foto struk, menentukan konteks transaksi, meminta data yang kurang bila perlu, lalu menyimpan transaksi ke Google Sheets. Untuk pertanyaan seperti kondisi keuangan, project paling untung, atau hutang antar dompet, bot mengambil data keuangan yang relevan dahulu lalu menyusun jawaban.

Buku ini dibuat untuk serah-terima admin. Bacalah Bab 3 sampai 7 sebelum mulai memakai bot. Bab 18 sampai 20 adalah bagian wajib untuk admin yang memegang akses sistem.

## Prinsip kerja yang wajib dipahami

- Google Sheets adalah sumber pencatatan operasional yang dilihat tim. Jangan menganggap transaksi tersimpan hanya karena pesan pertama sudah terkirim. Anggap selesai hanya setelah bot menampilkan hasil pencatatan atau laporan transaksi.
- AI membantu memahami bahasa natural dan OCR, tetapi nominal, dompet, project, hutang, serta penulisan akhir tetap divalidasi oleh rule bot dan data yang tersedia.
- Nama project adalah data penting. Tulislah konsisten dan jangan membuat variasi ejaan tanpa alasan.
- Di grup ramai, balasan singkat seperti angka, Ya, atau Batal harus selalu merupakan reply ke prompt bot yang benar.
- Bila bot meminta data tambahan, selesaikan dalam 15 menit. Sesudah itu sesi transaksi dapat kedaluwarsa agar jawaban lama tidak masuk ke transaksi yang salah.

## 1. Apa saja yang bisa dilakukan bot

Bot saat ini mendukung:

- Mencatat pemasukan dan pengeluaran project.
- Mencatat pengeluaran operasional kantor dengan dompet sumber dana.
- Mencatat transfer atau penyesuaian saldo dompet.
- Mencatat hutang antar dompet dan pelunasannya.
- Membaca foto struk atau nota melalui OCR, termasuk foto dahulu lalu teks konteks menyusul.
- Membantu koreksi nominal, scope transaksi, project, pembatalan, dan undo.
- Menyajikan saldo, status, laporan 7 hari, laporan 30 hari, daftar transaksi, link Google Sheets, audit data, dan export laporan PDF.
- Menjawab pertanyaan natural berbasis data nyata memakai perintah /tanya.
- Menerima alur bisnis yang sama melalui Telegram untuk teks dan foto.

Batasan saat ini:

- WhatsApp aktif menerima pesan teks serta gambar/media. Voice note tidak dirutekan sebagai input transaksi aktif. Jangan mengandalkan voice note.
- Dokumen, video, stiker, dan tipe pesan WhatsApp lain tidak diproses sebagai transaksi.
- Bot bukan pengganti approval bisnis. Untuk transaksi bernilai besar, tetap cocokkan nominal, dompet, dan project pada hasil bot sebelum menganggapnya final.
- Perintah /dompet dan /kategori ada di konfigurasi lama, tetapi bukan command pengguna yang aktif pada handler saat ini. Gunakan format transaksi atau prompt pilihan bot.

## 2. Peran dan hak akses

### Operator transaksi

Operator mengirim transaksi, menjawab prompt bot, mengirim struk, mengecek saldo atau laporan, dan mengoreksi transaksi yang baru dicatat.

### Admin keuangan

Admin memantau saldo dan hutang, menjaga penamaan project, memakai /audit setelah ada edit manual di Sheets, mengunduh laporan PDF, dan memastikan data tidak tercatat ganda.

### Owner atau technical operator

Owner atau technical operator mengelola allowlist nomor, koneksi WuzAPI/WhatsApp, Google Sheets, Groq, database state, deployment, dan health check. Secret seperti token, password database, credentials.json, atau API key tidak boleh dikirim ke chat grup.

Catatan akses: pada development lokal yang benar-benar memakai state non-durable, ALLOWED_SENDER_IDS yang kosong mengizinkan semua pengirim. Pada produksi, set ALLOWLIST_REQUIRED=1 dan isi allowlist dengan nomor atau user ID yang dipercaya; allowlist kosong akan fail-closed. STATE_STORE_REQUIRED=1 atau DURABLE_INBOX_REQUIRED=1 juga membuat allowlist kosong fail-closed meskipun FLASK_ENV masih development. SESSION_DELEGATE_IDS hanya untuk admin yang boleh meneruskan sesi user lain di grup dengan cara reply ke prompt yang benar.

## 3. Mulai dalam lima menit

1. Di chat pribadi, kirim /start lalu /help.
2. Coba satu transaksi project yang jelas:

   bayar tukang 2jt projek Villa Arta

3. Coba satu transaksi operasional:

   bayar wifi 450rb operasional kantor

4. Jika bot meminta dompet, jawab sesuai pilihan yang tampil.
5. Cek hasil dengan /saldo atau /list.
6. Jika salah, segera reply laporan transaksi bot lalu gunakan /revisi atau /undo.

Di grup, gunakan format berikut agar pesan pasti diproses:

   /catat bayar tukang 2jt projek Villa Arta

Atau mention bot, atau mulai teks dengan +catat. Jangan mengirim angka pilihan lepas di grup.

## 4. Peta data: dompet, company, dan sheet

| Dompet kanonis | Company project | Alias aman di chat | Fungsi |
| --- | --- | --- | --- |
| CV HB(101) | HOLLA atau HOJJA | CV HB, 101, Holla, Hojja | Dompet project dengan pemisahan company HOLLA/HOJJA |
| TX SBY(216) | TEXTURIN-Surabaya | TX SBY, 216, Surabaya, SBY | Dompet project Texturin Surabaya |
| TX BALI(087) | TEXTURIN-Bali | TX BALI, 087, Bali, Denpasar, Evan | Dompet project Texturin Bali |
| Operasional Kantor | Bukan company project | kantor, operasional, ops | Sheet biaya operasional, tetap memiliki dompet sumber dana |
| HUTANG | Bukan dompet | hutang, utang, pinjam | Register hutang antar dompet dengan status OPEN, PAID, atau CANCELLED |

Untuk project yang memakai CV HB, bot perlu tahu apakah transaksi milik HOLLA atau HOJJA. Jika belum jelas, bot akan meminta pilihan. Pada nama project CV HB, bot dapat menjaga prefix company, misalnya HOLLA - Villa Arta.

Gunakan alias yang spesifik. Kata Texturin atau TX saja dapat ambigu; lebih aman tulis TX SBY atau TX BALI.

## 5. Formula input yang paling aman

Gunakan pola:

   [aksi] [keterangan] [nominal] [scope] [nama project atau dompet bila perlu]

Contoh:

| Kebutuhan | Format yang disarankan |
| --- | --- |
| Pengeluaran project | bayar cat 1.250.000 projek Villa Arta |
| Pemasukan project | terima DP 20jt projek Villa Arta |
| Operasional kantor | bayar listrik 850rb operasional kantor |
| Update saldo absolut | update saldo dompet TX SBY 10jt |
| Transfer antar dompet | transfer 5jt dari CV HB ke TX SBY |
| Project memakai dana dompet lain | bayar tukang 5jt projek Villa Arta utang dari TX SBY |
| Pelunasan hutang natural | bayar hutang ke TX SBY 2jt |

Nominal yang aman:

- 150000
- 150.000
- Rp 150.000
- 150rb
- 1,5jt atau 1.5jt
- 2 juta

Hindari angka tanpa konteks seperti 2 atau 150. Di grup, angka lepas hanya aman bila merupakan reply ke pilihan bot yang masih aktif.

Kata scope yang paling membantu:

- Project: projek, project, proyek, prj.
- Operasional: kantor, operasional, operational, ops.
- Penyesuaian saldo: update saldo, set saldo, samakan saldo, isi dompet.
- Hutang antar dompet: utang, hutang, pinjam, minjam, dari, ke, diikuti alias dompet yang jelas.

## 6. Cara bot memproses transaksi

Alur normal:

1. Bot menerima pesan dan mencegah event webhook yang sama diproses berulang.
2. Bot mengekstrak nominal, arah pemasukan/pengeluaran, keterangan, scope, dompet, company, dan nama project.
3. Jika konteks cukup jelas dan mode cepat aktif, bot bisa mencatat langsung.
4. Jika ada data kurang atau ambigu, bot meminta pilihan scope, dompet, company, nama project, atau konfirmasi.
5. Setelah write ke Sheets berhasil, bot mengirim hasil transaksi. Jika write gagal, bot harus menyatakan bahwa data belum dicatat.

Yang biasa membuat bot bertanya:

- Nominal tidak ditemukan atau tidak masuk akal.
- Pesan tidak menjelaskan project versus operasional.
- Operasional belum memiliki dompet sumber dana.
- CV HB terdeteksi tetapi HOLLA/HOJJA belum jelas.
- Nama project baru, typo, atau mirip beberapa project.
- Ada indikasi hutang tetapi dompet pemberi/penerima belum jelas.

Cara menjawab prompt:

- Balas angka yang benar sesuai prompt terbaru.
- Di grup, reply pesan prompt bot, baru ketik angka atau Ya.
- Gunakan /cancel jika konteksnya sudah salah sebelum tersimpan.
- Jika prompt salah, tulis salah, ralat, atau bukan agar bot mengulang pemilihan yang relevan.

## 7. Perbedaan chat pribadi dan grup

### Chat pribadi

- Alias teks non-slash banyak diterima, misalnya status, saldo, laporan, help, atau bantuan.
- Bila tidak ada ambiguitas, alur terasa lebih longgar.
- Revisi yang tidak me-reply masih dapat mencoba memakai laporan transaksi terakhir, tetapi reply tetap lebih aman.

### Grup

- Command harus memakai slash, misalnya /saldo, /laporan, atau /tanya.
- Bot mengabaikan chat santai bila tidak melihat sinyal transaksi atau panggilan bot yang cukup.
- Agar transaksi pasti diproses, gunakan /catat, +catat, mention bot, atau reply ke prompt bot.
- Jawaban Ya, Batal, atau angka harus reply prompt yang benar. Ini mencegah jawaban Anda menyelesaikan transaksi milik orang lain.
- Revisi di grup wajib reply pesan laporan bot Transaksi Tercatat. Tanpa reply, bot menolak revisi karena targetnya tidak aman.

### Telegram

Telegram memakai logika pencatatan yang sama: kirim teks atau foto struk, lalu ikuti konfirmasi bot bila diminta. Gunakan command dengan garis miring dan balas pesan bot untuk jawaban singkat agar konteks tetap aman, terutama di grup. Voice note belum menjadi input aktif pada alur Telegram maupun WhatsApp.

## 8. Mencatat transaksi project

### Project berjalan

Format paling aman:

   bayar [item] [nominal] projek [Nama Project]

Contoh:

   beli keramik 1.2jt projek Villa Arta
   bayar tukang plafon 2jt projek Ruko Panjer
   terima termin 15jt projek Villa Arta

Bot akan mencari project yang sudah dikenal pada dompet/company yang sesuai. Jika nama tepat dan konteks jelas, bot bisa lanjut otomatis. Jika nama mirip atau belum valid, bot meminta nama yang benar atau konfirmasi saran.

### Project baru

Gunakan nama yang rapi dan konsisten. Saat bot menganggap project baru, ia meminta konfirmasi agar biaya operasional tidak salah dibuat sebagai project baru. Setelah Anda menyetujui project baru, transaksi awal dapat diberi marker (Start).

Contoh:

   terima DP 20jt projek Rumah Bu Rina

atau:

   bayar tukang 5jt projek Rumah Bu Rina

Jika transaksi kedua adalah benar-benar project baru, pilih opsi lanjut sebagai project baru saat diminta.

### Project selesai

Untuk pemasukan project yang berupa pelunasan, tulis konteksnya jelas:

   terima pelunasan 10jt projek Villa Arta

Bot dapat memberi marker (Selesai) pada project. Marker ini hanya berasal dari pemasukan dengan kata seperti pelunasan, lunas, final payment, penyelesaian, selesai, kelar, atau beres. Jangan menggunakan kata tersebut pada transaksi yang belum benar-benar menutup project.

## 9. Mencatat operasional kantor

Gunakan kata kantor atau operasional agar bot tidak salah menaruh biaya lapangan sebagai biaya kantor.

Contoh:

   bayar wifi 450rb operasional kantor
   beli ATK 150rb kantor
   bayar listrik kantor 850rb

Alur:

1. Bot mendeteksi scope Operasional Kantor.
2. Bot meminta dompet sumber dana jika belum tertulis.
3. Pilih dompet yang tampil: CV HB, TX SBY, atau TX BALI.
4. Bot menyimpan biaya di sheet Operasional Kantor dengan tag sumber dompet.

Kategori dibaca otomatis dari konteks. Contoh umum:

- gaji, honor, payroll -> Gaji
- listrik, PLN, air, PDAM, wifi, internet -> ListrikAir
- makan, minum, snack, konsumsi -> Konsumsi
- ATK, alat, peralatan -> Peralatan
- kata lain -> Lain Lain

Jika bot menebak project padahal transaksi kantor, jawab atau revisi ke operational. Sebaliknya, jika biaya lapangan salah masuk operasional, revisi ke project dan tulis nama project.

## 10. Transfer dan update saldo dompet

### Transfer antar dompet

Gunakan arah yang jelas:

   transfer 5jt dari CV HB ke TX SBY

atau gunakan /catat di grup. Sebut dompet sumber dan tujuan dengan alias spesifik agar transaksi tidak menjadi pertanyaan klarifikasi.

### Update saldo absolut

Gunakan update saldo jika angka yang Anda tulis adalah saldo akhir aktual, bukan nominal transaksi baru.

   update saldo dompet TX SBY 10jt
   set saldo dompet CV HB 25jt
   samakan saldo TX BALI 7.5jt

Bot membaca saldo saat ini, menghitung selisih terhadap target, lalu mencatat penyesuaian pada Saldo Umum sebagai pemasukan atau pengeluaran. Jika saldo sudah sama, bot tidak membuat transaksi baru.

Jangan memakai update saldo untuk memindahkan dana antar dompet. Untuk perpindahan uang, tulis transfer dengan arah dari dan ke.

## 11. Hutang antar dompet dan pelunasan

### Membuat hutang antar dompet

Gunakan saat transaksi dibiayai dompet lain. Contoh:

   bayar tukang 5jt projek Villa Arta utang dari TX SBY

Untuk operasional:

   bayar wifi 450rb operasional kantor pinjam CV HB

Jika bot memahami arah dompet, sistem:

- Mencatat transaksi utama pada project atau operasional yang tepat.
- Mencatat pengeluaran pada dompet pemberi dana untuk mencerminkan dana yang dipinjamkan.
- Menambah entry HUTANG berstatus OPEN, dengan dompet pemakai sebagai yang berhutang dan dompet pemberi sebagai yang dihutangi.

Selalu sebut dompet pemberi dana secara eksplisit. Kata pinjam tanpa alias dompet tidak cukup aman.

### Melunasi hutang

Cara paling terkontrol:

   /lunas 3

Nomor 3 adalah nomor hutang OPEN pada register HUTANG. Command ini langsung memproses nomor yang dipilih, jadi cek nomor terlebih dahulu.

Cara natural:

   bayar hutang ke TX SBY 2jt
   pelunasan hutang ke CV HB 5jt
   bayar hutang no 3

Jika kandidat lebih dari satu, bot menampilkan daftar. Balas angka pilihan dengan reply di grup. Untuk kandidat tunggal, balas Ya atau angka 1 jika bot meminta konfirmasi. Status akhir menjadi PAID. Hutang yang terkait transaksi yang dihapus atau dibatalkan dapat berubah menjadi CANCELLED.

Hutang antar dompet dipisahkan dari profit pada laporan. Jangan menyamakan saldo dompet dengan laba rugi tanpa melihat status hutang OPEN.

## 12. Foto struk, nota, dan OCR

Cara terbaik adalah kirim foto dan caption dalam satu pesan:

   struk beli cat 1.250.000 projek Villa Arta utang dari TX SBY

Contoh operasional:

   struk bensin 205rb operasional kantor

Bot menggunakan OCR untuk membaca transaksi, nominal, dan petunjuk rekening sumber bila tersedia. Caption tetap sangat penting karena foto sering tidak memiliki konteks project atau operasional.

Foto dulu lalu teks:

1. Kirim foto struk.
2. Kirim teks konteks transaksi dalam sesi aktif, paling aman segera dan tidak lebih dari 15 menit.
3. Di grup, reply foto atau prompt bot bila tersedia.

Praktik foto yang baik:

- Pastikan nominal, tanggal, dan nomor rekening sumber terlihat tajam.
- Hindari foto gelap, blur, terlalu miring, atau terpotong.
- Jangan mengirim screenshot transfer lama tanpa menyebutkan apakah itu transaksi baru yang harus dicatat.
- Jika ada biaya admin transfer, tulis jelas atau biarkan OCR membacanya. Bot memiliki validasi agar fee tidak keliru dianggap nominal utama.

Jika bot memberi pesan bahwa gambar tidak terbaca atau bukan struk, kirim ulang gambar lebih jelas atau tulis transaksi manual. Jika provider mengirim event gambar tanpa media, bot hanya bisa mencoba caption; tanpa caption transaksi tidak dapat dibuat.

## 13. Menanyakan data dengan /tanya

Perintah /tanya dipakai ketika Anda ingin jawaban analitis, bukan mencatat transaksi. Bot lebih dahulu merencanakan maksud pertanyaan, mengambil data transaksi relevan, lalu menyusun jawaban. AI tidak boleh menjawab dari tebakan ketika data yang diperlukan tidak ada.

Contoh:

| Kebutuhan | Contoh |
| --- | --- |
| Ringkasan umum | /tanya cek keuangan hari ini |
| Project tertentu | /tanya total pengeluaran projek Villa Arta 30 hari |
| Laba/rugi project | /tanya projek Villa Arta untung atau rugi bulan ini |
| Dompet tertentu | /tanya dompet TX SBY pengeluaran minggu ini |
| Hutang dompet | /tanya hutang TX SBY |
| Ranking | /tanya projek paling untung bulan ini |
| Aktivitas project | /tanya project yang sedang berjalan |
| Project selesai | /tanya project selesai sejak awal |
| Rincian | /tanya rincian transaksi project Villa Arta |
| Kategori atau biaya | /tanya biaya gaji 30 hari terakhir |

Kata waktu:

- hari ini -> 1 hari
- kemarin -> 2 hari terakhir
- minggu ini -> 7 hari
- bulan ini -> 30 hari
- tahun ini -> 365 hari
- 14 hari, 2 minggu, 3 bulan, 1 tahun -> periode relatif
- sejak awal, alltime, total, keseluruhan -> sepanjang data

Untuk ranking paling gacor, gunakan kata yang jelas tentang ukuran yang dimaksud. Contoh yang lebih aman:

   /tanya project paling untung bulan ini
   /tanya project dengan pemasukan terbesar 30 hari
   /tanya dompet paling aktif minggu ini

## 14. Monitoring, laporan, dan export

### /status

Memberikan dashboard ringkas yang memakai ringkasan data keuangan. Gunakan sebagai cek umum.

### /saldo

Menampilkan saldo nyata tiap dompet. Saldo memperhitungkan pemasukan/pengeluaran dompet, potongan operasional, dan penyesuaian hutang OPEN. Jadi angka saldo tidak boleh dibaca sebagai profit.

### /list

Menampilkan maksimal 15 transaksi terbaru dari 7 hari terakhir.

### /laporan dan /laporan30

- /laporan: ringkasan 7 hari.
- /laporan30: ringkasan 30 hari.

Keduanya mencakup pemasukan, pengeluaran, profit, total transaksi, snapshot saldo dompet, serta statistik hutang antar dompet. Laporan menyatakan bahwa hutang antar dompet dipisah dari metrik profit.

### /audit

Perintah read-only untuk memeriksa data Sheets yang kemungkinan rusak akibat edit manual, seperti nominal kosong/tidak numerik, tipe transaksi tidak dikenal, atau dompet/company tidak dikenal. Perintah ini tidak mengubah data. Setelah /audit menemukan masalah, admin harus membetulkan baris terkait dengan hati-hati dan menjalankan /audit lagi.

### /link

Mengirim link Google Sheets yang sedang dikonfigurasi. Pastikan hanya user yang memang boleh melihat data keuangan yang berada dalam allowlist atau grup bot.

### /exportpdf

Membuat laporan PDF transaksi untuk periode yang memiliki data.

Format periode yang didukung:

   /exportpdf 2026-01
   /exportpdf 01-2026
   /exportpdf Januari 2026
   /exportpdf 2025-09-22 2025-10-22
   /exportpdf 22-09-2025 22-10-2025

Tanpa argumen, bot memakai bulan berjalan. Jika periode kosong, bot tidak membuat PDF agar tidak menghasilkan laporan yang menyesatkan.

## 15. Referensi command lengkap

| Command | Fungsi | Catatan penting |
| --- | --- | --- |
| /start | Intro singkat bot | Di chat pribadi dapat memakai start, mulai, hi, atau halo. |
| /help atau /bantuan | Bantuan penggunaan | Di chat pribadi dapat memakai help atau bantuan. |
| /status atau /cek | Dashboard ringkas | Alias tanpa slash hanya untuk chat pribadi. |
| /saldo | Saldo nyata dompet | Termasuk pengaruh operasional dan hutang OPEN. |
| /list | Riwayat 7 hari | Maksimal 15 transaksi. |
| /laporan | Laporan 7 hari | Termasuk statistik hutang dan saldo snapshot. |
| /laporan30 | Laporan 30 hari | Gunakan untuk rekap bulanan cepat. |
| /tanya [pertanyaan] | Tanya data keuangan natural | Di grup wajib slash. |
| /exportpdf [periode] | Kirim laporan PDF | Bulanan atau rentang tanggal. |
| /link | Link Google Sheets | Periksa akses penerima. |
| /audit | Audit integritas baris Sheets | Read-only, berguna setelah edit manual. |
| /lunas [nomor] | Lunasi hutang OPEN bernomor | Cek nomor sebelum mengirim. |
| /revisi [isi] | Koreksi transaksi | Reply laporan transaksi bot, wajib di grup. |
| /undo | Hapus transaksi terakhir/target dengan konfirmasi | Reply laporan bot di grup. |
| /cancel | Batalkan sesi transaksi aktif | Tidak menghapus transaksi yang sudah tersimpan. |
| /catat [transaksi] | Paksa proses sebagai transaksi | Sangat dianjurkan di grup. |

## 16. Revisi, undo, dan pembatalan

### Revisi

Reply pesan laporan bot Transaksi Tercatat, lalu gunakan:

   /revisi 150rb
   /revisi fee 3rb
   /revisi operational
   /revisi project Villa Arta

Contoh pertama mengubah nominal utama. Contoh kedua untuk fee/admin yang tercatat sebagai item terpisah. Dua contoh terakhir memindahkan scope ke operasional atau project. Setelah revisi, baca hasil ringkasan yang dikirim bot dan cek /list atau /saldo jika nominalnya material.

Di grup, /revisi tanpa reply akan ditolak. Di chat pribadi, bot mungkin memakai laporan terakhir sebagai fallback, tetapi reply tetap cara paling aman.

### Undo

Reply laporan transaksi bot lalu kirim:

   /undo

Bot meminta konfirmasi hapus. Balas 1, Ya, Hapus, OK, atau Oke untuk menyetujui; balas 2, Batal, Tidak, atau Cancel untuk membatalkan penghapusan. Undo hanya untuk kesalahan transaksi yang baru diketahui. Jangan menggunakan undo sebagai pengganti koreksi akuntansi yang sudah dibahas atau direkonsiliasi.

### Cancel

Gunakan:

   /cancel

Cancel menghentikan sesi yang masih menunggu pilihan, nominal, project, atau konfirmasi. Cancel tidak menarik kembali transaksi yang sudah berhasil tertulis ke Sheets.

## 17. Pesan error dan tindakan yang benar

| Pesan atau kondisi | Makna | Tindakan |
| --- | --- | --- |
| Nominal tidak terbaca | Bot tidak menemukan nominal yang valid | Kirim ulang dengan 150rb, 1.5jt, atau 150000 dan konteksnya. |
| Dompet tidak terdeteksi | Sumber atau target dompet belum jelas | Jawab pilihan bot atau tulis CV HB, TX SBY, atau TX BALI. |
| Nama project belum valid | Nama baru, typo, atau ambigu | Ketik nama lengkap yang benar dan konsisten. |
| Tidak ada pertanyaan aktif | Sesi kedaluwarsa atau reply salah | Kirim transaksi ulang; di grup reply prompt terbaru. |
| Di grup wajib reply | Jawaban singkat tidak terikat sesi | Reply prompt bot, lalu jawab angka atau Ya. |
| Gagal menyimpan ke spreadsheet | Write belum berhasil | Jangan menganggap tersimpan. Tunggu sebentar, cek /list atau Sheets, lalu kirim ulang sekali bila memang belum ada. |
| Gagal membaca spreadsheet | Data laporan tidak dapat dibaca saat itu | Coba lagi sekitar satu menit; jangan mengedit banyak baris sambil menunggu. |
| Gambar tidak terbaca | OCR gagal membaca bukti | Foto ulang dengan jelas atau ketik transaksi manual. |
| Periode PDF kosong atau salah | Tidak ada transaksi atau format periode keliru | Gunakan format contoh /exportpdf 2026-01. |
| Akses ditolak | Pengirim belum diizinkan | Admin harus menambah identitas pengirim ke allowlist lalu redeploy/restart bila diperlukan. |

Jika bot mengirim status Menganalisis data atau Memproses, tunggu jawaban akhir sebelum mengirim command baru. Bila tidak ada jawaban akhir, admin teknis perlu memeriksa log WuzAPI dan acknowledgement pengiriman, bukan langsung menganggap AI masih bekerja.

## 18. Rutinitas admin keuangan

### Setiap hari

1. Catat transaksi dengan scope dan dompet jelas.
2. Selesaikan prompt sebelum 15 menit.
3. Gunakan /saldo bila ada perpindahan kas atau transaksi operasional.
4. Tinjau hutang OPEN; jangan menunggu sampai terlupa.
5. Bila terjadi kesalahan, revisi atau undo segera sambil reply laporan bot.

### Setiap minggu

1. Kirim /laporan.
2. Cek /list untuk anomali transaksi terbaru.
3. Tinjau project yang aktif dan project yang selesai melalui /tanya.
4. Pastikan pelunasan project ditulis dengan kata pelunasan atau lunas hanya bila project benar-benar selesai.
5. Jalankan /audit bila ada perubahan manual pada Google Sheets.

### Setiap bulan

1. Kirim /laporan30.
2. Export PDF bulan yang berakhir.
3. Rekonsiliasi saldo aktual tiap dompet memakai update saldo bila memang diperlukan.
4. Selesaikan atau investigasi hutang OPEN.
5. Rapikan variasi nama project sebelum membuat laporan manajemen.

## 19. Operasi teknis dan kesehatan sistem

Bagian ini untuk owner atau technical operator, bukan user biasa.

### Konfigurasi minimum produksi

- GOOGLE_SHEETS_ID dan akses service account ke spreadsheet.
- WUZAPI_DOMAIN dan WUZAPI_TOKEN untuk WhatsApp.
- GROQ_API_KEY atau GROQ_API_KEYS untuk pemahaman bahasa natural/OCR yang memakai model.
- GROQ_TIMEOUT_SECONDS (default 30 detik, dibatasi 1-120 detik) agar kegagalan provider tidak menggantungkan webhook.
- ALLOWED_SENDER_IDS untuk membatasi pengguna; ALLOWLIST_REQUIRED=1 wajib di produksi agar konfigurasi kosong tidak membuka bot ke semua pengirim. Mode state durable juga fail-closed bila allowlist kosong.
- TELEGRAM_WEBHOOK_SECRET dan WUZAPI_WEBHOOK_SECRET untuk autentikasi inbound webhook; WEBHOOK_SECRET_REQUIRED=1 wajib di produksi. Mode state durable juga mewajibkan secret bila flag eksplisit tidak diberikan.
- STATE_STORE_BACKEND=postgres dan STATE_DATABASE_URL untuk state transaksi yang tahan restart.
- STATE_STORE_REQUIRED=1 dan DURABLE_INBOX_REQUIRED=1 bila produksi harus gagal tertutup ketika state durable tidak tersedia.

Simpan semua nilai tersebut hanya sebagai environment variable deployment. Jangan masukkan secret ke dokumen ini, chat, source repository, atau Google Sheets.

### Health check

Endpoint GET /health melaporkan healthy, degraded, atau unhealthy serta status inbox transaksi dan security.missing. Pada konfigurasi durable wajib, status inbox yang tidak durable membuat layanan mengembalikan 503 agar webhook tidak dianggap aman saat data tidak bisa dipersistenkan. Di produksi, allowlist kosong atau secret webhook yang belum diisi juga mengembalikan 503 sampai konfigurasi dilengkapi.

### Keandalan transaksi

Sebelum pesan WhatsApp diproses, event transaksi dicatat ke inbox durable bila database dikonfigurasi. Ini mendukung deduplikasi, penggabungan foto dan teks, serta recovery bila proses terputus. Background worker mencoba pemulihan event yang tertunda atau retryable.

Google Sheets tetap harus dijaga sebagai data operasional. Hindari edit struktur header, sheet, atau kolom tanpa perubahan source yang sesuai. Sesudah edit manual, jalankan /audit.

### Pengiriman balasan WhatsApp

WuzAPI dapat membalas HTTP 200 tetapi payload provider tetap perlu menunjukkan acknowledgement pengiriman. Log sukses yang sehat mencatat WuzAPI Send acknowledged beserta message_id dan panjang body. Jika log menyatakan send outcome unknown atau not acknowledged, periksa sesi WuzAPI, token, konektivitas provider, lalu tes dengan /help setelah layanan stabil.

## 20. Checklist serah-terima admin

Sebelum admin lama menyerahkan bot:

- Berikan PDF ini dan tunjukkan chat contoh project, operasional, hutang, revisi, serta /tanya.
- Jelaskan tiga dompet dan pemisahan HOLLA/HOJJA pada CV HB.
- Pastikan admin baru tahu bahwa di grup harus reply prompt bot.
- Tunjukkan Google Sheets, tab Operasional Kantor, dan register HUTANG.
- Perlihatkan cara membaca /saldo, /laporan, /laporan30, dan /audit.
- Jelaskan bahwa voice note WhatsApp tidak digunakan sebagai input aktif.
- Jelaskan kapan memakai update saldo dan kapan memakai transfer.
- Pastikan nomor admin baru berada dalam ALLOWED_SENDER_IDS bila allowlist diaktifkan.
- Serahkan akses deployment dan secret hanya melalui password manager atau mekanisme aman, bukan chat.
- Jalankan uji penerimaan: satu project, satu operasional, satu /tanya, satu /lunas dummy pada data uji, satu /exportpdf periode yang berisi data, lalu /audit.

## Lampiran A. Template copy-paste

Project berjalan:

   bayar [item] [nominal] projek [Nama Project]

DP atau pemasukan project:

   terima DP [nominal] projek [Nama Project]

Operasional:

   bayar [item] [nominal] operasional kantor

Transfer:

   transfer [nominal] dari [dompet sumber] ke [dompet tujuan]

Update saldo aktual:

   update saldo dompet [dompet] [saldo akhir]

Project dengan hutang:

   bayar [item] [nominal] projek [Nama Project] utang dari [dompet pemberi]

Operasional dengan hutang:

   bayar [item] [nominal] operasional kantor pinjam [dompet pemberi]

Pertanyaan data:

   /tanya [pertanyaan yang menyebut metrik dan periode]

Revisi:

   reply laporan bot lalu /revisi [nominal baru]

## Lampiran B. Uji penerimaan setelah perubahan sistem

Gunakan contoh berikut pada lingkungan uji atau dengan penanda data uji:

1. dp 100.000 project pak rina tx sby
2. bayar wifi 450rb operasional kantor
3. jawab pilihan dompet atau Ya bila diminta
4. /tanya project paling untung bulan ini
5. /laporan30
6. Kirim struk dengan caption
7. bayar wifi 450rb operasional kantor pinjam CV HB
8. Reply laporan bot lalu /revisi atau /undo pada transaksi uji
9. /audit

Jika hasil nominal, dompet, scope, project, hutang, atau status tidak sesuai, hentikan penggunaan untuk transaksi material dan minta technical operator memeriksa log serta data Sheets sebelum melanjutkan.

## Riwayat dan pemeliharaan dokumen

Dokumen ini harus diperbarui bersama perubahan source yang memengaruhi command, format input, dompet, company, kategori, input media, alur konfirmasi, atau data tujuan. Pemilik dokumen wajib menjalankan kembali contoh uji pada Lampiran B setiap kali deploy besar dilakukan.
