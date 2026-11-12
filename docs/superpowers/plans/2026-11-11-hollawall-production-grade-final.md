# Hollawall Financial Command Center — Final Production-Grade Implementation Plan

**Tanggal plan:** 2026-11-11

**Baseline immutable:** `0ee6a95e253bdb616382fca86a8c7285f7d02fd4`

**Parent baseline:** `c0add4509ae207c920b1b6472d7cbb5d7afd5ab5`

**Repository:** `Naufalspurnomo/keuangan`

**Status baseline:** **NO-GO / BELUM BOLEH DINYATAKAN OK**

**Jenis dokumen:** Kontrak implementasi, acceptance, release, rollback, dan Definition of Done

> Dokumen ini adalah sumber kebenaran pekerjaan final. Implementasi tidak dinyatakan selesai karena komponennya ada, test unit hijau, build berhasil, atau halaman dapat dibuka. Status `OK` hanya sah setelah seluruh task wajib dan seluruh acceptance gate dalam dokumen ini mempunyai bukti yang dapat dibaca ulang.

---

## 1. Kontrak misi

```yaml
objektif:
  Mengubah sistem keuangan Hollawall menjadi Financial Command Center production-grade
  yang memangkas input manual, menjaga integritas data, dan mempertahankan seluruh fitur
  yang sudah disepakati ketika release baru dipasang.

penerimaan:
  - Tujuh menu kanonis berfungsi end-to-end sesuai tanggung jawab masing-masing.
  - Proyek menjadi pusat workflow operasional dan finansial per proyek.
  - Project Candles/candlestick lifecycle tampil pada route Proyek production.
  - Transaksi proyek mendukung create, read, correction, reversal, dan audit readback.
  - Pinjaman antar-dompet dapat ditautkan ke proyek tanpa mencemari pendapatan/biaya.
  - PostgreSQL menjadi otoritas online terstruktur; Google Sheets menjadi backup/export.
  - WhatsApp dan Dashboard memakai finance core serta aturan bisnis yang sama.
  - Seluruh angka Dashboard, Dompet, Hutang, Proyek, dan Laporan dapat direkonsiliasi.
  - CI, security, browser, accessibility, performance, backup, restore, deploy,
    rollback, dan post-deploy verification seluruhnya lulus.

batasan:
  - Quotation visual tetap dibuat di Canva.
  - Negosiasi klien tetap melalui WhatsApp/telepon.
  - Tidak ada hard delete transaksi finansial production.
  - Tidak ada transaksi palsu yang ditinggalkan pada data production.
  - Tidak ada dual source of truth permanen.
  - Tidak ada tombol mati, form palsu, atau fitur yang hanya ter-render tanpa persistence.
  - Tidak ada penghapusan fitur lama sebelum parity test terhadap route kanonis lulus.

otoritas:
  inspeksi_repo: true
  modifikasi_code: true
  migrasi_staging: true
  test_staging: true
  build_release: true
  deploy_production: hanya_setelah_semua_gate_hijau
  penghapusan_data_irreversible: false

mode: implementation_plan_then_evidence_gated_execution
fase_saat_ini: audit_dan_plan
blocker_saat_ini:
  - Production Gate baseline gagal.
  - Route Proyek production masih bercabang dan kehilangan candlestick/tahun.
  - Transaction correction/reversal belum tersedia.
  - Hutang production belum mempunyai write lifecycle yang nyata.
  - Authority kas masih Google Sheets, bertentangan dengan target Sheets sebagai backup.
  - Provenance SHA Rumahweb belum dapat dibuktikan.
selesai_terverifikasi: false
```

### Amendment operator 2026-11-12 — Fresh-zero production ledger

Keputusan eksplisit operator ini menggantikan seluruh requirement historical backfill,
shadow import, mapping 1.139 row, dan disposition 76 review item sebagai syarat go-live:

- Dashboard production dimulai dari ledger PostgreSQL kosong.
- Data historis Google Sheets tidak diimpor ke PostgreSQL dan tidak ditampilkan di Dashboard.
- Google Sheets lama dipertahankan sebagai arsip read-only terpisah, bukan business input.
- Setelah activation, Google Sheets baru hanya menerima derived one-way export dari PostgreSQL.
- Go-live wajib membuktikan canonical transaction/debt/project count dan balance mulai nol,
  lalu hanya berubah melalui mutation terotorisasi dari Dashboard atau WhatsApp.
- Tool ekstraksi/backfill yang sudah dibuat dipertahankan sebagai recovery/audit tooling,
  tetapi tidak boleh dijalankan terhadap production tanpa keputusan operator baru.

Jika bagian lain dokumen ini mewajibkan import atau rekonsiliasi histori lama, amendment ini menang.

### Invariant misi

1. **Satu fakta finansial mempunyai satu otoritas kanonis.**
2. **Setiap mutasi dapat diaudit, diulang secara idempotent, dan dibaca kembali dari otoritas.**
3. **Project ID UUID, bukan nama proyek, menjadi identitas lintas Dashboard, WhatsApp, API, transaksi, dokumen, hutang, dan laporan.**
4. **Pinjaman antar-dompet bukan pendapatan dan bukan biaya.**
5. **Operasional Kantor tidak boleh memuat transaksi proyek, termasuk transaksi proyek yang gagal dipetakan.**
6. **Fitur production tidak boleh hilang karena fallback, feature flag, atau route precedence.**
7. **Build/deploy SHA baru tidak boleh dipromosikan apabila required CI merah.**
8. **Release tidak selesai sebelum readback production membuktikan outcome pengguna.**
9. **WhatsApp dan Dashboard adalah interface; finance core adalah penjaga aturan bisnis.**
10. **Google Sheets target akhir adalah backup/export portabel, bukan primary writer kedua.**

---

## 2. Mengapa sistem ini dibutuhkan

Workflow admin sekarang terlalu manual dan terfragmentasi:

1. Proyek dan klien baru muncul.
2. Admin membuat quotation di Canva.
3. Admin meminta persetujuan Boss.
4. Negosiasi berlangsung manual melalui WhatsApp/telepon.
5. Quotation direvisi di Canva sampai klien setuju.
6. Invoice DP 30–50% dibuat.
7. Proyek berjalan.
8. Boss mengirim screenshot transaksi BCA kepada admin.
9. Admin membaca sumber dana/dompet dari screenshot satu per satu.
10. Admin mengetik transaksi ke spreadsheet.
11. Cashflow, pelunasan, dan gaji worker dicatat manual.
12. Invoice pelunasan dibuat.
13. Admin berpindah ke spreadsheet lain untuk menghitung laba/rugi.

Masalah bisnisnya bukan sekadar tampilan:

- input ganda;
- sumber data tersebar;
- risiko salah dompet dan salah proyek;
- laba/rugi terlambat diketahui;
- hutang antar-dompet dapat tercampur dengan arus eksternal;
- Boss tidak mendapat satu tampilan kesehatan perusahaan;
- test komponen dapat hijau sementara alur online hilang;
- deployment dapat mengganti route tanpa memverifikasi seluruh fitur yang pernah disepakati.

**Tujuan Dashboard:** menjadi command center Boss/admin untuk melihat, membuat, mengoreksi, dan menelusuri aktivitas keuangan tanpa kembali ke workflow spreadsheet manual. Dashboard tidak menggantikan Canva untuk desain quotation atau negosiasi manusia; Dashboard menghubungkan hasil aktivitas tersebut ke proyek, dokumen, transaksi, hutang, dan laporan yang dapat diaudit.

---

## 3. Fakta baseline `0ee6a95`

Commit ini bukan patch kecil. Dibanding parent `c0add45`, commit mengubah **57 file**, menambah **2.648 baris**, menghapus **340 baris**, termasuk design system baru dan mapping transaksi proyek kanonis.

### Yang sudah ada

- React Dashboard di Rumahweb dengan login/session PHP dan same-origin proxy.
- Flask/Gunicorn backend di Koyeb.
- PostgreSQL untuk durability, workflow proyek/dokumen, audit, inbox, idempotency, dan projection.
- Google Sheets sebagai otoritas kas saat ini.
- WhatsApp/WuzAPI sebagai interface input dan output.
- Project master, Sales Order, invoice, receipt, quotation handoff, PDF, dan evidence.
- Presensi berbasis private filesystem Rumahweb dan delivery WhatsApp.
- PDF report transaksi.
- Candlestick/lifecycle chart dan year selector sebagai komponen source.
- Atomic Rumahweb deployment scripts dan backup/restore tooling.

### Defect blocker yang terbukti

1. **Dua implementasi Proyek berjalan paralel.**
   - `ProductionProjectsWorkspace` menggunakan `ProjectRecord` dari Project API.
   - `ProjectCommandCenter` menggunakan `FinanceProject` dari snapshot.
   - Route production mendahulukan implementasi pertama.

2. **Candlestick dan pemilih tahun tidak tampil pada jalur production normal.**
   - Fitur ada di `ProjectCommandCenter`/`ProjectLifecycleMarketChart`.
   - Jalur itu menjadi fallback ketika Project API production tidak tersedia.

3. **Dua implementasi detail proyek.**
   - `ProjectDetailWorkspace` untuk production.
   - `ProjectTransactionsWorkspace` untuk snapshot/demo/fallback.

4. **Transaksi proyek production hanya create/read.**
   - `transaction_correction_reversal` pada live health masih `false`.
   - Update/delete aman belum tersedia.

5. **Menu Hutang menampilkan aksi yang tidak memiliki production write path.**
   - UI memberi kesan CRUD, tetapi form/mutasi tidak aktif pada live read-only workspace.
   - Model hutang belum memiliki `project_id`.

6. **Transaksi proyek yatim dapat salah diklasifikasikan sebagai Operasional Kantor.**
   - Adapter memakai kondisi `scope === office || !project`.

7. **Drill-down proyek masih memakai nama pada sebagian flow.**
   - Nama dapat berubah atau duplikat; UUID wajib.

8. **Status `cancelled` dinormalisasi menjadi `completed`.**
   - Analitik dapat salah menyatakan proyek batal sebagai proyek selesai.

9. **Aksi duplikat dan salah tempat.**
   - Dua entry point biaya kantor pada production.
   - Ekspor CSV global berada di menu Proyek, bukan Laporan.

10. **Current CI baseline gagal.**
    - Production Gate untuk SHA ini gagal pada browser visual acceptance.
    - Security checks yang berada setelah browser test tidak sempat berjalan.

11. **Deployment tidak terkunci ke gate.**
    - Koyeb sudah melayani SHA `0ee6a95...` walau Production Gate merah.
    - Rumahweb tidak mempunyai endpoint/manifest yang membuktikan Git SHA aktif.

12. **Tidak ada authenticated post-deploy E2E.**
    - Smoke public dapat hijau walau fitur setelah login hilang.

13. **Sheets/PostgreSQL masih memiliki authority yang tidak sesuai target akhir.**
    - Saat ini Sheets adalah otoritas transaksi kas.
    - PostgreSQL `financial_ledger` hanya projection/mirror best-effort.
    - Target Boss adalah database online sebagai otoritas dan Sheets sebagai backup.

14. **Backlog review perlu ditangani.**
    - Live health saat audit: `backlog=76`, `needs_review=76`, `oldest_review_age_seconds=9743211`.

### Verdict baseline

`0ee6a95` adalah **baseline desain dan canonical mapping**, bukan release final. Statusnya **NO-GO** sampai seluruh task di bawah selesai.

---

## 4. Arsitektur penuh saat ini

```text
Pengguna WhatsApp
    |
    v
WuzAPI
    |
    v
Koyeb: Flask/Gunicorn
    |-- durable transaction_inbox ----------> PostgreSQL
    |-- finance parser / OCR / validation
    |-- dashboard/project/document APIs
    |-- retry workers / idempotency
    |
    +-- transaksi kas saat ini -------------> Google Sheets [CURRENT AUTHORITY]
    |                                             |
    |                                             +--> PostgreSQL financial_ledger [projection]
    |
    +-- project/document/evidence ----------> PostgreSQL [AUTHORITY]
    +-- balasan ----------------------------> WuzAPI/WhatsApp

Browser Boss/Admin
    |
    v
Rumahweb /admin
    |-- React static app
    |-- PHP login/session/CSRF
    |-- PHP same-origin allowlisted proxy
    |
    +----------------------------------------> Koyeb APIs

Browser Karyawan
    |
    v
Rumahweb /absen
    +--> private .hollawall-presensi/events.json + photos [AUTHORITY PRESENSI]
              |
              +--> leased outbox --> Koyeb --> WuzAPI --> grup WhatsApp

Backup
    |-- pg_dump PostgreSQL
    |-- export Google Sheets
    |-- private Presensi tree
    +--> manifest/hash --> encrypted archive --> offsite + downloaded-byte readback
```

### Peran setiap plane

- **WhatsApp/WuzAPI:** interface operasional cepat, transport bukti, reply, dan notifikasi. Bukan database.
- **Dashboard React:** command center Boss/admin. Tidak menyimpan authority di browser.
- **Rumahweb PHP:** auth/session, CSRF, same-origin proxy, static frontend, private presensi storage.
- **Koyeb Flask:** API/orchestrator/business-service runtime.
- **PostgreSQL:** authority proyek/dokumen/audit saat ini; target authority seluruh ledger online.
- **Google Sheets:** authority kas saat ini; target backup/export/reconciliation view.
- **Presensi private filesystem:** authority presensi; tidak otomatis menjadi payroll authority.
- **Canva:** authoring visual quotation; Dashboard menyimpan handoff/status/artifact reference.
- **WhatsApp/telepon manusia:** negosiasi; tetap manual.

---

## 5. Arsitektur target yang dikomit

### Keputusan A — PostgreSQL menjadi otoritas finansial online

Target akhir:

```text
WhatsApp dan Dashboard
        |
        v
Finance Command API + deterministic finance core
        |
        v
PostgreSQL [CANONICAL AUTHORITY]
        |-- financial transactions
        |-- projects
        |-- inter-wallet debts
        |-- office operations
        |-- documents/evidence
        |-- immutable audit/reversal
        |-- idempotency/outbox/inbox
        |
        +--> outbox/export worker --> Google Sheets [BACKUP/PORTABLE EXPORT]
```

Aturan cutover:

- Tidak boleh menyalakan dua primary writer.
- Ledger PostgreSQL production diinisialisasi fresh-zero; data Sheets historis tidak diimpor.
- Rekonsiliasi awal membuktikan canonical count, amount, balance, debt, dan project finance sama dengan nol.
- Sheets historis dibekukan sebagai arsip read-only dan dikeluarkan dari business reads.
- Cutover dilakukan dengan feature flag terkontrol.
- Setelah cutover, Sheets hanya menerima export dari canonical ledger; tidak menerima write bisnis langsung.
- Export Sheets yang gagal tidak membatalkan commit PostgreSQL; kegagalan masuk outbox/alert dan dapat di-retry.
- Setiap row export membawa canonical transaction UUID dan revision/reversal reference.

### Keputusan B — Satu Project Domain kanonis

- Identitas: PostgreSQL `projects.id` UUID.
- Satu list route, satu detail route, satu API contract.
- Snapshot keuangan memperkaya proyek berdasarkan UUID; tidak membuat proyek kedua.
- Nama proyek hanya label.
- Fallback tidak mengganti pengalaman menjadi implementasi lain; fallback menjadi explicit degraded/error state.

### Keputusan C — Ledger immutable

Permintaan CRUD transaksi diterjemahkan secara aman:

- **Create:** membuat transaksi.
- **Read:** list/detail/readback.
- **Update:** membuat correction revision dengan alasan; record awal tetap ada.
- **Delete:** membuat reversal/void auditable; bukan hard delete.

Setiap mutasi menyimpan:

- actor;
- timestamp;
- idempotency key;
- reason;
- source channel;
- original transaction ID;
- corrected/reversed transaction ID;
- before/after canonical payload;
- project UUID;
- wallet UUID/code;
- authoritative readback.

### Keputusan D — Hutang antar-dompet memakai double-entry internal

Model minimal:

- debt UUID;
- lender wallet;
- borrower wallet;
- optional project UUID;
- principal;
- outstanding;
- currency;
- issued date;
- optional due date;
- status;
- repayment events;
- correction/reversal events;
- actor/audit/idempotency.

Aturan:

- pencairan memindahkan kas antar-dompet;
- total kas grup tidak berubah;
- pencairan bukan pendapatan proyek;
- repayment bukan biaya proyek;
- outstanding terlihat sebagai receivable lender dan payable borrower;
- proyek dapat memiliki funding/loan exposure terpisah dari profit/loss.

### Keputusan E — Tujuh menu, tujuh tanggung jawab

Satu business action mempunyai **satu canonical form dan satu service**. Shortcut pada menu lain hanya deep-link ke canonical form dengan context prefilled; shortcut tidak menduplikasi modal, validasi, atau state management.

---

## 6. Kontrak tujuh menu

### 6.1 Dashboard

Nama final: **Dashboard**, menggantikan “Ringkasan”.

Tujuan:

- ringkasan perusahaan;
- KPI lintas unit;
- alerts dan exception;
- tren singkat;
- proyek aktif/berisiko;
- posisi dompet;
- hutang jatuh tempo;
- data quality/review queue;
- drill-down ke menu pemilik data.

Bukan tempat:

- form transaksi;
- form hutang;
- form operasional kantor;
- report builder lengkap;
- tabel proyek lengkap.

Acceptance:

- Semua KPI mempunyai “as of” timestamp dan sumber.
- Angka dapat direkonsiliasi ke menu detail.
- Tidak ada primary mutation button.
- Alert mempunyai tujuan jelas dan deep-link.

### 6.2 Arus Kas

Tujuan:

- arus masuk/keluar eksternal;
- tren periode;
- filter tahun/perusahaan/dompet/proyek;
- drill-down ledger;
- membedakan external flow dari internal transfer/debt.

Shortcut yang diizinkan:

- “Tambah transaksi proyek” membuka Proyek/pemilih proyek lalu canonical transaction form.
- “Catat operasional kantor” membuka menu Operasional Kantor dan canonical office form.

Acceptance:

- Shortcut tidak merender form kedua.
- Transfer/hutang internal tidak menambah pendapatan/biaya grup.
- Drill-down memakai UUID.
- Filter bertahan pada refresh/shareable route jika aman.

### 6.3 Dompet

Tiga dompet/unit keuangan kanonis:

- `CV HB(101)` untuk HOLLA dan HOJJA;
- `TX SBY(216)` untuk TEXTURIN Surabaya;
- `TX BALI(087)` untuk TEXTURIN Bali.

Tujuan:

- saldo tersedia;
- arus masuk/keluar;
- net flow;
- receivable/payable antar-dompet;
- saldo adjusted;
- runway;
- aging;
- aktivitas terakhir;
- status `Healthy`, `Watch`, atau `Critical` beserta alasan.

Acceptance:

- Tidak menyebut tiga dompet sebagai tiga proyek.
- Health rule deterministik, terdokumentasi, dan diuji.
- Angka adjusted cocok dengan menu Hutang.
- Tidak ada form transaksi generik yang menduplikasi menu pemilik operasi.

### 6.4 Proyek

Tujuan utama sistem.

Halaman awal wajib:

- year selector;
- filter unit/perusahaan/status/search;
- Project Candles/candlestick lifecycle production;
- portfolio/list kanonis;
- tombol canonical “Tambah proyek”.

Semantik Project Candles:

- satu candle = satu proyek;
- bukan OHLC palsu;
- body = tanggal mulai hingga tanggal selesai atau `as of`;
- wick/marker aktivitas = aktivitas finansial pertama hingga terakhir;
- warna = lifecycle/age state yang terdokumentasi;
- proyek selesai/batal tetap dapat dilihat pada filter yang tepat;
- unit dipisahkan jelas: HOLLA, HOJJA, TEXTURIN Surabaya, TEXTURIN Bali;
- zoom, pan, keyboard, dan touch tidak mengunci scroll halaman;
- klik/focus candle membuka UUID proyek yang benar;
- mobile memakai selector/ringkasan yang tetap usable, bukan empat canvas raksasa sekaligus.

Detail proyek wajib:

- Overview;
- Transaksi;
- Pinjaman/Hutang;
- Profitability;
- Presensi;
- Dokumen;
- Audit/activity.

Create project wajib menyimpan:

- nama;
- klien;
- unit/perusahaan;
- dompet utama;
- tanggal mulai;
- nilai kontrak jika tersedia;
- status;
- metadata quotation/handoff;
- UUID.

Acceptance:

- Project baru muncul pada list, chart, filter tahun, dan detail setelah authoritative readback.
- Refresh tidak menghilangkan project.
- Tidak ada implementasi fallback kedua.
- Status `cancelled` tetap `cancelled`, bukan `completed`.

### 6.5 Operasional Kantor

Tujuan:

- biaya nonproyek;
- transaksi kantor yang memakai salah satu dompet perusahaan;
- correction/reversal auditable;
- kategori dan bukti.

Acceptance:

- Hanya transaksi `scope=office` yang tampil.
- `project_id` tidak dikenal masuk “Perlu Ditinjau”, bukan kantor.
- Satu canonical “Catat biaya” button.
- Tidak ada proyek dalam pilihan transaksi kantor.

### 6.6 Hutang

Tujuan:

- seluruh posisi hutang/piutang antar bank/dompet perusahaan;
- pencairan;
- repayment penuh/parsial;
- aging/due date;
- status;
- koreksi/reversal;
- optional linkage ke proyek.

Acceptance:

- Semua tombol yang terlihat bekerja end-to-end.
- Shortcut dari proyek membuka form Hutang yang sama dengan project UUID prefilled.
- Pencairan/repayment netral terhadap revenue dan expense.
- Posisi cocok pada Proyek dan Dompet.

### 6.7 Laporan

Tujuan:

- satu pusat preview dan export;
- PDF sebagai acceptance minimum;
- CSV jika tetap dipertahankan, hanya berada di menu ini.

Report type wajib:

- cashflow;
- wallet position;
- project profitability;
- project lifecycle;
- office operations;
- debt aging;
- transaction audit/correction/reversal.

Acceptance:

- PDF memuat judul, scope, filter, periode, generated-at, data-through, dan total.
- Project report memakai UUID.
- Internal debt tidak tercampur sebagai external cashflow.
- PDF dapat dibuka dan totalnya cocok dengan preview.

---

## 7. Flow end-to-end wajib

### Flow A — Proyek Pak Rahmat

1. Admin login.
2. Buka Proyek.
3. Pilih tahun.
4. Klik Tambah proyek.
5. Buat “Pak Rahmat”, unit yang benar, dompet utama `TX BALI(087)`.
6. Authoritative readback mengembalikan UUID.
7. Proyek muncul di list dan Project Candles.
8. Buka candle/list item.
9. Tambah pemasukan DP.
10. Tambah biaya worker/material.
11. Refresh browser; transaksi tetap muncul hanya di proyek Pak Rahmat.
12. Profitability berubah sesuai transaksi eksternal.
13. Koreksi salah nominal dengan correction event.
14. Balik transaksi uji dengan reversal event.
15. Audit menunjukkan semua event tanpa kehilangan histori.

### Flow B — Pinjaman proyek

1. Dari detail Pak Rahmat, klik shortcut “Ajukan/catat pinjaman”.
2. Menu Hutang terbuka dengan project UUID dan borrower `TX BALI(087)` terisi.
3. Pilih lender wallet lain.
4. Catat principal dan due date.
5. Wallet lender/borrower berubah berlawanan.
6. Total kas grup tidak berubah.
7. Profit proyek tidak berubah karena pinjaman.
8. Outstanding muncul pada Proyek, Dompet, dan Hutang.
9. Catat repayment parsial lalu penuh.
10. Status dan audit konsisten setelah refresh.

### Flow C — WhatsApp ke Dashboard

1. Pesan/screenshot transaksi masuk melalui WuzAPI.
2. Durable inbox menyimpan ingress sebelum processing.
3. OCR/parser menghasilkan candidate, bukan langsung mempercayai model.
4. Finance core memvalidasi wallet/project/type/amount/date.
5. Konfirmasi jika confidence/field tidak cukup.
6. PostgreSQL canonical commit hanya sekali.
7. Dashboard menampilkan transaksi setelah refresh/realtime invalidation.
8. Sheets backup/export menerima canonical UUID.
9. Retry tidak menduplikasi transaksi.

### Flow D — Operasional Kantor

1. Buka menu Operasional Kantor.
2. Catat biaya dan dompet sumber.
3. Record tersimpan dengan `scope=office`, tanpa `project_id`.
4. Record muncul di kantor, arus kas, dompet, dan laporan.
5. Record tidak muncul pada proyek.
6. Correction/reversal memperbarui semua projection secara konsisten.

### Flow E — Laporan

1. Pilih report type, periode, unit, wallet, project, status.
2. Preview memakai data authority yang sama dengan UI.
3. Export PDF.
4. Parse/readback PDF membuktikan judul, periode, total, dan row count.
5. Hash artifact dicatat untuk release acceptance.

---

## 8. Rencana implementasi wajib

Semua checkbox di bagian ini wajib selesai. Label P0/P1/P2 menunjukkan urutan, **bukan optionality**.

### Phase 0 — Freeze baseline dan feature contract

#### PG-000 — Bekukan baseline dan evidence

- [ ] Simpan full diff `c0add45..0ee6a95` sebagai audit artifact.
- [ ] Simpan hasil CI baseline dan live health baseline.
- [ ] Simpan screenshot/video tujuh menu desktop/mobile baseline.
- [ ] Catat current SHA Koyeb dan status Rumahweb yang belum terbukti.
- [ ] Jangan mengubah production selama desain data dan migration plan belum lulus review.

Acceptance:

- Evidence mempunyai timestamp, SHA, target, dan hash.
- Baseline dapat direproduksi tanpa bergantung pada chat.

#### PG-002 — Exact baseline execution guard

Tasks:

- [ ] Buat branch/worktree implementasi langsung dari `0ee6a95e253bdb616382fca86a8c7285f7d02fd4`; jangan mulai dari parent `c0add45`.
- [ ] Fail local/CI bila merge-base candidate tidak memuat exact baseline tersebut.
- [ ] Catat baseline SHA, implementation HEAD, dirty status, submodule state, serta hash dependency lockfiles pada evidence setiap release candidate.
- [ ] Setiap commit/perubahan wajib merujuk minimal satu task ID plan ini.
- [ ] Candidate diff selalu dihitung `0ee6a95...candidate`, bukan berdasarkan working tree lama.

Acceptance:

- `git merge-base --is-ancestor 0ee6a95e253bdb616382fca86a8c7285f7d02fd4 <candidate>` exit `0`.
- Implementation base yang tercatat adalah exact `0ee6a95...`; tidak ada perubahan baseline yang diam-diam hilang.
- Candidate tree bersih sebelum build release dan seluruh diff dapat ditelusuri ke task ID.

#### PG-003 — External dependency dan environment readiness gate

Inventory wajib:

- [ ] GitHub branch protection dan required-check administration.
- [ ] Koyeb immutable image promotion, environment config, previous-image recovery.
- [ ] PostgreSQL SSL, migration role, runtime role, backup/restore, capacity, dan PITR capability.
- [ ] Rumahweb staging path, PHP modules, private filesystem, atomic activation, dan rollback access.
- [ ] WuzAPI webhook, outbound delivery, retry, serta allowlisted owner test identity.
- [ ] Google service account, quota, protected export workbook/ranges, dan backup permissions.
- [ ] Offsite backup remote dan alert destination.
- [ ] Authenticated browser test account dan secret-delivery mechanism.

Acceptance:

- Setiap dependency mempunyai owner, tested permission, expiry/rotation record, quota/capacity, dan non-production verification.
- Missing access atau permission menjadi blocker sebelum migrasi production, bukan alasan membuat workaround tersembunyi.
- RPO/RTO disetujui sebelum implementasi storage/cutover dikunci.

#### PG-001 — Buat feature registry anti-regression

Files:

- Create: `docs/FEATURE_MATRIX.md`
- Create: `dashboard/src/featureManifest.ts`
- Test: `dashboard/src/featureManifest.test.ts`

Tasks:

- [ ] Daftarkan tujuh route kanonis.
- [ ] Daftarkan required component/action/capability tiap route.
- [ ] Tandai owner menu untuk setiap business action.
- [ ] Tandai fitur manual yang sengaja tetap di Canva/WhatsApp.
- [ ] Tambahkan test yang gagal bila route/fitur wajib hilang.

Acceptance:

- Candlestick, year selector, project transactions, project borrowing, office, debt, dan PDF tidak dapat hilang diam-diam tanpa test gagal.

### Phase 1 — Authority dan data model

#### PG-100 — ADR authority migration

Files:

- Create: `docs/architecture/ADR-009-postgres-financial-authority.md`
- Update: `docs/FINANCE_AGENT.md`
- Update: `docs/PRODUCTION_STATE.md`
- Update/deprecate: `docs/DASHBOARD_OPERATIONS.md`

Tasks:

- [ ] Dokumentasikan current Sheets authority dan target PostgreSQL authority.
- [ ] Definisikan commit point, consistency, retry, reconciliation, export, recovery.
- [ ] Tandai dokumen VPS/Apache lama sebagai deprecated jika tidak lagi berlaku.
- [ ] Bekukan no-dual-primary rule.

Acceptance:

- Tidak ada dokumen operasional aktif yang bertentangan tentang source of truth atau target hosting.

#### PG-101 — Canonical financial schema dan posting contract

Files:

- Create: `dashboard_api/migrations/009_canonical_financial_ledger.sql`
- Create: `dashboard_api/migrations/010_interwallet_debts.sql`
- Create: `dashboard_api/migrations/011_financial_outbox_and_reconciliation.sql`
- Create: versioned migration ledger/checksum.
- Update: migration runner/schema health.

Tasks:

- [ ] Pisahkan canonical dimensions `business_units` dan `wallets`, termasuk kasus HOLLA/HOJJA berbagi `CV HB(101)`.
- [ ] Model wallet opening balance dengan effective timestamp, currency, actor, provenance, dan source snapshot hash.
- [ ] Model auditable balance-adjustment events; larang silent absolute balance overwrite.
- [ ] Model canonical transaction UUID, scope, project UUID, wallet, company/unit, amount, type, category, occurred-at, source, evidence, actor, dan revision chain.
- [ ] Model balanced postings dan klasifikasi external flow versus internal transfer.
- [ ] Model correction/reversal effective-state; cegah cycle, double reversal, dan mutasi original.
- [ ] Model debt disbursement/repayment/correction/reversal serta atomic posting links.
- [ ] Model immutable project status-transition events dengan `completed_at`, `cancelled_at`, dan archive visibility semantics.
- [ ] Model export outbox dan reconciliation checkpoints.
- [ ] Bekukan currency IDR, integer rounding, timezone `Asia/Jakarta`, cutoff, dan aturan inklusivitas periode.
- [ ] Tambahkan constraints nilai, wallet, project/scope exclusivity, currency, status, serta referential integrity document/evidence/allocation.
- [ ] Tambahkan forward-compatible indexes dan query plans.

Migration execution contract:

- [ ] Migration hanya dijalankan oleh one-shot release job dengan PostgreSQL advisory lock dan restricted migration role.
- [ ] Hapus startup DDL dari Gunicorn/application runtime.
- [ ] Startup aplikasi hanya melakukan read-only schema-version/checksum compatibility verification.
- [ ] Definisikan compatible application/schema version range dan fail readiness bila schema partial, checksum mismatch, terlalu lama, atau terlalu baru.

Acceptance:

- Invalid wallet/project/scope ditolak database/service.
- Hard delete ledger diblokir.
- Untuk setiap wallet dan cutoff: `opening balance + effective postings = displayed available balance`.
- Setiap debt disbursement/repayment menghasilkan balanced internal postings secara atomik dan tidak mengubah group cash/P&L.
- Correction/reversal tidak dapat membentuk cycle, tidak dapat dibalik dua kali, dan tidak memutasi original event.
- Migration rerun menghasilkan no-op terverifikasi; interrupted migration tidak dapat melaporkan ready.
- Menjalankan banyak Gunicorn worker tidak pernah mengeksekusi DDL.
- Existing project/document/evidence/allocation references tetap kompatibel.

#### PG-102 — Historical archive isolation dan fresh-zero bootstrap

Files:

- Create: `scripts/backfill_sheets_to_postgres.py`
- Create: `scripts/reconcile_financial_authorities.py`
- Create: `scripts/export_postgres_to_sheets.py`
- Create: versioned migration manifest schema.
- Tests: `tests/financial_authority_migration_test.py`

Tasks:

- [ ] Bekukan snapshot/hash Sheets historis sebagai arsip owner-scoped read-only.
- [ ] Pastikan tidak ada importer/backfill production yang terjadwal atau aktif.
- [ ] Inisialisasi canonical transaction, posting, debt, project-finance, dan opening balance dengan count/amount nol.
- [ ] Simpan activation evidence yang menyatakan `historical_import=false` dan cutoff fresh-zero.
- [ ] Tambahkan regression test yang melarang archive source menjadi business read/input production.
- [ ] Export backup idempotent ke Sheets dengan canonical UUID + revision/reversal sequence.

Acceptance:

- Arsip historis tetap utuh dan dapat dipulihkan tanpa masuk ke canonical production totals.
- Fresh bootstrap menghasilkan zero transaction/debt/project-finance rows dan zero wallet balances.
- Dashboard/WhatsApp readback awal nol; mutation canary pertama muncul tepat sekali.
- Tidak ada direct Sheets business read/write setelah activation.

#### PG-103 — Protected one-way Sheets backup/export

Tasks:

- [ ] Gunakan dedicated canonical export workbook atau protected isolated tabs.
- [ ] Batasi business user dari edit canonical export ranges; service account hanya mendapat minimum permissions.
- [ ] Bekukan canonical export schema, uniqueness key, ordering, revision/reversal representation, dan cutoff metadata.
- [ ] Gunakan transaction UUID + revision/reversal sequence sebagai export key.
- [ ] Buat upsert idempotent yang aman pada crash setelah remote write tetapi sebelum outbox acknowledgement.
- [ ] Detect missing, duplicate, manually edited, reordered, dan stale exports.
- [ ] Jika Sheets disebut backup, lakukan emergency reconstruction drill dari export ke disposable PostgreSQL.

Acceptance:

- Human edit tidak pernah menjadi canonical input.
- Injected crash-window menghasilkan tepat satu effective exported record.
- Export drift dan lag diukur terhadap PostgreSQL pada cutoff yang sama.
- Sheets hanya derived copy; tidak ada business primary writer.

### Phase 2 — Deterministic finance core dan API

#### PG-200 — Canonical transaction service

Files:

- Refactor: `services/dashboard_transaction_service.py`
- Refactor/replace: `services/ledger_store.py`
- Update: `services/row_validator.py`
- Update: `dashboard_api/routes.py`
- Create if needed: `services/financial_transaction_repository.py`

Tasks:

- [ ] Satu service dipakai Dashboard dan WhatsApp.
- [ ] Create, correction, reversal, read/detail/list.
- [ ] Idempotency pada request dan side effect.
- [ ] Optimistic concurrency/version check.
- [ ] Authoritative PostgreSQL readback.
- [ ] Outbox export Sheets setelah commit.
- [ ] Capability hanya `true` setelah full route siap.

Acceptance:

- Crash/retry menghasilkan satu transaksi.
- Same key/different payload ditolak.
- Correction/reversal tidak menghapus original.
- Saldo dan profitability dihitung dari effective ledger.

#### PG-201 — Canonical debt service

Files:

- Create: `services/interwallet_debt_service.py`
- Create: `dashboard_api/debt_routes.py`
- Update: `dashboard_api/__init__.py`
- Tests: `tests/interwallet_debt_service_test.py`, `tests/interwallet_debt_route_test.py`

Tasks:

- [ ] Create debt.
- [ ] Partial/full repayment.
- [ ] Correction/reversal/archive.
- [ ] Optional project link.
- [ ] Double-entry internal transfer.
- [ ] Aging/outstanding/read model.
- [ ] Idempotency, audit, authorization, CSRF.

Acceptance:

- Group cash invariant selalu terjaga.
- Revenue/expense invariant tidak berubah.
- Project/wallet/debt views identik setelah refresh.

#### PG-202 — Project UUID everywhere

Files:

- Update: `dashboard/src/snapshot.ts`
- Update: `dashboard/src/transactionMappings.ts`
- Update: `dashboard/src/projectDocumentApi.ts`
- Update: backend snapshot/projection code.

Tasks:

- [ ] Hilangkan join berdasarkan nama.
- [ ] Hilangkan synthetic/fallback project identity pada production.
- [ ] Tambahkan explicit unmapped bucket.
- [ ] Perbaiki `cancelled` mapping.

Acceptance:

- Rename proyek tidak memutus transaksi.
- Nama duplikat tidak membuka proyek salah.
- Unmapped tidak dihitung sebagai office.

#### PG-203 — WhatsApp canonical integration

Files:

- Update: `handlers/wuzapi_webhook.py`
- Update: finance parser/confirmation handlers.
- Update: retry/inbox workers.

Tasks:

- [ ] Commit WhatsApp melalui service yang sama dengan Dashboard.
- [ ] Project/wallet selection memakai canonical IDs/codes.
- [ ] OCR output selalu divalidasi deterministik.
- [ ] Preserve durable inbox and dedup.
- [ ] Export Sheets melalui outbox, bukan direct primary write.

Acceptance:

- Pesan retry tidak menduplikasi.
- Transaksi WhatsApp muncul di Dashboard dan report.
- Dashboard correction terlihat pada audit WhatsApp-origin transaction.

#### PG-204 — Retirement seluruh legacy Sheets business call-site

Tasks:

- [ ] Inventaris setiap direct Sheets read/write untuk transaksi, saldo, project lookup, office, Hutang, WhatsApp query/summary, report, dan dashboard snapshot.
- [ ] Klasifikasikan setiap call sebagai source import, derived export, backup/reconciliation, atau forbidden production business access.
- [ ] Migrasikan seluruh business read/write ke canonical finance core/PostgreSQL.
- [ ] Tambahkan CI architecture test yang melarang production modules mengimpor atau memanggil forbidden direct Sheets business functions.
- [ ] Setelah cutover, allowlist akses Sheets hanya untuk import, reconciliation, export, dan backup modules.

Acceptance:

- WhatsApp balance/project/debt/report/transaction queries membaca PostgreSQL.
- Dashboard dan report tidak membaca business truth dari Sheets.
- Architecture test gagal bila direct business access ke Sheets ditambahkan kembali.

#### PG-205 — Authentication, authorization, dan actor trust contract

Files:

- Create: `docs/architecture/ADR-010-dashboard-auth-actor-trust.md`
- Update: Rumahweb PHP session/proxy, Koyeb auth, audit event schema, secret runbook.

Tasks:

- [ ] Bekukan model principal: Boss dan Admin adalah actor terpisah dengan role/capability eksplisit; tidak ada generic owner untuk seluruh mutation.
- [ ] Hapus compiled/default proxy-token hash; production fail closed bila secret/config hilang.
- [ ] Gunakan short-lived signed upstream identity assertion atau mekanisme replay-resistant setara dari Rumahweb ke Koyeb.
- [ ] Bind assertion ke actor, role, audience, issued-at, expiry, request/method/body hash atau nonce.
- [ ] Restrict/disable direct Koyeb dashboard login/mutation ketika production wajib melalui Rumahweb.
- [ ] Definisikan secret rotation, overlap, revocation, session renewal, logout, emergency access, dan audit.

Acceptance:

- Setiap financial mutation audit menunjukkan actor autentik sebenarnya.
- Missing/default/expired/replayed/wrong-origin/wrong-audience credentials fail closed.
- Actor admin tidak memperoleh Boss-only capability.
- Secret rotation drill lulus tanpa kehilangan data atau membuka bypass.

#### PG-206 — Canonical finance metric specification

Files:

- Create: `docs/finance/CANONICAL_METRICS.md`
- Create: versioned SQL/service oracle + fixtures.

Definisi wajib:

- cash balance, available balance, adjusted balance;
- receivable/payable exposure;
- external inflow/outflow dan group net cashflow;
- project revenue, cost, cashflow, gross profit, margin, contribution;
- runway;
- wallet `Healthy`/`Watch`/`Critical` thresholds;
- debt aging buckets;
- review/quarantine exclusion;
- correction/reversal effective state;
- timezone, cutoff, period inclusivity, IDR integer rounding.

Acceptance:

- Setiap metric mempunyai formula, inclusion/exclusion rules, canonical query/service version, dan fixture dengan expected result.
- Dashboard, Wallet, Project, Debt, WhatsApp, dan Reports dibandingkan ke oracle, bukan hanya dibandingkan satu sama lain.
- Perubahan formula memerlukan version bump, migration/compatibility note, dan regression evidence.

### Phase 3 — Shell dan information architecture

#### PG-300 — Satu shell, tujuh route

Files:

- Refactor: `dashboard/src/App.tsx`
- Remove after parity: `dashboard/src/LiveFinanceApp.tsx`
- Remove/archive after parity: unused generic `TransactionsWorkspace` route/component.

Tasks:

- [ ] Rename Ringkasan menjadi Dashboard.
- [ ] Pertahankan tepat tujuh menu utama.
- [ ] “Perlu Ditinjau” menjadi alert/subroute, bukan menu utama kedelapan kecuali requirement baru disetujui.
- [ ] Route detail memakai stable UUID query/path.
- [ ] Mobile breadcrumb mempertahankan nama proyek.
- [ ] Loading/error/degraded/empty state eksplisit.

Acceptance:

- Sidebar desktop dan mobile mempunyai tujuh menu yang sama.
- Refresh/deep-link menjaga route.
- Tidak ada route production yang jatuh ke demo component.

#### PG-301 — Action ownership dan anti-duplication

Files:

- Update: `dashboard/src/FinancePages.tsx`
- Update: route action configuration dan feature registry.

Tasks:

- [ ] Buat action ownership map.
- [ ] Beri setiap visible interactive control stable action ID dan owner route.
- [ ] Satu canonical form untuk transaction, office, debt, project.
- [ ] Shortcut hanya deep-link dengan context; shortcut tidak me-mount form kedua.
- [ ] Enumerate seluruh control untuk setiap capability combination.
- [ ] Exercise setiap enabled control sampai terminal success, validation, atau intentional navigation state.
- [ ] Hidden/disabled control mempunyai explicit capability reason.
- [ ] Pindahkan seluruh export ke Laporan.
- [ ] Hapus tombol mati dan tombol duplikat.

Acceptance:

- Zero unregistered visible controls.
- Zero enabled controls tanpa handler yang dieksekusi dalam acceptance test.
- Tepat tujuh top-level navigation entries pada desktop dan mobile.
- Tidak ada dua modal/form untuk business action sama.
- Shortcut selalu membuka canonical owner form dengan context yang benar.

#### PG-302 — Project lifecycle transition contract

Tasks:

- [ ] Definisikan allowed/forbidden transition untuk `planned`, `active`, `completed`, `cancelled`.
- [ ] Simpan immutable status transition event dan effective timestamp.
- [ ] Jadikan archive sebagai visibility property/event, bukan financial completion status.
- [ ] Definisikan candle year assignment, start/end, color, dan filter untuk seluruh status.
- [ ] Definisikan efek transition pada transaction eligibility, invoice, debt, presensi, dan reports.

Acceptance:

- Cancellation tidak pernah menulis completion status/date.
- Archived project mempertahankan status finansial dan histori.
- Candle start/end/color/year dan detail UUID dapat direproduksi dari canonical lifecycle events.
- Forbidden transition ditolak backend dan tidak ditampilkan UI.

### Phase 4 — Implementasi setiap menu

#### PG-400 — Dashboard

Files:

- Refactor: `dashboard/src/FinancePages.tsx` / `OverviewWorkspace`
- Add focused dashboard selector/view tests.

Tasks:

- [ ] KPI perusahaan, cash, active projects, margin, wallet alerts, debt aging, review backlog.
- [ ] Tren ringkas dan drill-down.
- [ ] Timestamp/data-through.
- [ ] Hilangkan detail panjang yang dimiliki route lain.

Acceptance:

- Dashboard menjawab “apa yang perlu diperhatikan hari ini?” dalam satu viewport awal.
- Semua angka drill-down cocok.

#### PG-410 — Arus Kas

Files:

- Refactor: `dashboard/src/FinancialOperationsWorkspace.tsx`

Tasks:

- [ ] External cashflow chart dan ledger.
- [ ] Filter tahun/periode/unit/wallet/project/type.
- [ ] Internal transfer toggle terpisah.
- [ ] Deep-link shortcut ke canonical forms.

Acceptance:

- Hutang internal tidak mengubah external net cashflow.
- Filter dan PDF reconciliation lulus.

#### PG-420 — Dompet

Files:

- Refactor: wallet workspace in `dashboard/src/FinancialOperationsWorkspace.tsx`
- Create selectors/helpers with unit tests.

Tasks:

- [ ] Tiga wallet identities kanonis.
- [ ] Available/adjusted balance.
- [ ] Receivable/payable exposure.
- [ ] Runway, net flow, aging, last activity.
- [ ] Deterministic health state dan reason.

Acceptance:

- Wallet total reconcile ke ledger dan debt.
- Tidak ada istilah “tiga proyek” untuk wallet.

#### PG-430 — Proyek kanonis

Files:

- Merge/refactor: `dashboard/src/ProductionProjectsWorkspace.tsx`
- Merge/refactor: `dashboard/src/ProjectCommandCenter.tsx`
- Retain/integrate: `dashboard/src/ProjectLifecycleMarketChart.tsx`
- Refactor: `dashboard/src/ProjectDetailWorkspace.tsx`
- Remove after parity: `dashboard/src/ProjectTransactionsWorkspace.tsx`

Tasks:

- [ ] Satu portfolio workspace berdasarkan Project API UUID.
- [ ] Year selector production.
- [ ] Candlestick production.
- [ ] Create/edit/status/archive project.
- [ ] Detail tabs Overview/Transaksi/Pinjaman/Profitability/Presensi/Dokumen/Audit.
- [ ] Feature flags tidak boleh mengganti UI menjadi implementation kedua.

Acceptance:

- Project Candles terlihat setelah login production.
- Create/read/refresh/deep-link lulus.
- Semua tab memakai project UUID yang sama.

#### PG-431 — Project Candles production hardening

Files:

- Update: `dashboard/src/ProjectLifecycleMarketChart.tsx`
- Update: `dashboard/src/project-lifecycle-market-chart.css`
- Tests: unit, browser, visual, keyboard, touch.

Tasks:

- [ ] Freeze candle semantics.
- [ ] Use canonical lifecycle and activity dates.
- [ ] Preserve completed/cancelled filtering.
- [ ] Touch and keyboard action equivalence.
- [ ] Mobile selector/summarized mode.
- [ ] Prevent nested-scroll trap.

Acceptance:

- No fake OHLC labels.
- Candle click opens exact UUID.
- 320px–desktop usable without page overflow.

#### PG-440 — Project transaction lifecycle

Files:

- Refactor: `dashboard/src/ProjectProfitabilityWorkspace.tsx`
- Update: transaction form/API client.

Tasks:

- [ ] Create with project locked.
- [ ] Detail/readback.
- [ ] Correction with reason.
- [ ] Reversal with confirmation and reason.
- [ ] Evidence attachment.
- [ ] Duplicate-submit prevention.
- [ ] Loading/success/validation/API-error states.

Acceptance:

- Full Flow A passes E2E.
- Transaction never appears on another project.
- Refresh and new session preserve data.

#### PG-450 — Operasional Kantor

Files:

- Refactor: office workspace/form.
- Fix: `dashboard/src/snapshot.ts` classification.

Tasks:

- [ ] Canonical office expense create/read/correct/reverse.
- [ ] Wallet source and categories.
- [ ] Evidence/audit.
- [ ] Unmapped transaction review state.

Acceptance:

- Unknown project ID does not alter office totals.
- One office mutation entry point.

#### PG-460 — Hutang

Files:

- Refactor: `DebtWorkspace`/debt forms.
- Create: debt API client and tests.

Tasks:

- [ ] Live create/read/repay/correct/reverse/archive.
- [ ] Optional project UUID.
- [ ] Aging and outstanding.
- [ ] Prefilled deep-link from project.
- [ ] Responsive table/card.

Acceptance:

- Full Flow B passes E2E.
- Zero dead controls.

#### PG-470 — Laporan kanonis

Files:

- Refactor: `dashboard/src/ReportsWorkspace.tsx`
- Create: versioned report-query API dan canonical report dataset schema.
- Create/update: deterministic report renderer dan tests.

Tasks:

- [ ] Centralize PDF/CSV export di route Laporan.
- [ ] Generate report dataset dari PostgreSQL effective ledger pada canonical cutoff.
- [ ] Gunakan server-side PDF renderer, atau bila browser renderer dipertahankan, embed exact dataset hash dan lakukan server-side verification sebelum artifact diterima.
- [ ] Implement required report types.
- [ ] Definisikan pagination, full-row retrieval, sorting, locale, fonts, totals, empty report, timeout, retention.
- [ ] Simpan report type, actor, filters, cutoff, dataset hash, renderer version, artifact hash.
- [ ] Include filter metadata, data-through, generated-at.
- [ ] Add independent SQL/service oracle dan PDF parse/readback tests.

Acceptance:

- Canonical oracle total = preview total = parsed PDF total.
- Multi-page output tidak kehilangan row.
- Unicode Bahasa Indonesia, zero rows, correction, reversal, dan internal debt exclusion teruji.
- PDF opens, text layer readable, dan artifact dapat dilacak ke canonical dataset hash.

### Phase 5 — Cross-domain workflows

#### PG-500 — Quotation and document boundary

Tasks:

- [ ] Keep Canva as visual authoring source.
- [ ] Store quotation handoff, version, approval status, external artifact reference.
- [ ] Preserve manual negotiation status without pretending automation.
- [ ] Link accepted quotation to project/Sales Order/invoice.
- [ ] Verify invoice DP and final payment allocations.

Acceptance:

- No duplicate Canva editor is built.
- Commercial document lifecycle remains auditable.

#### PG-510 — Presensi integration

Tasks:

- [ ] Keep presensi authority in private Rumahweb storage unless a separate migration is approved.
- [ ] Link display to canonical project UUID through controlled mapping.
- [ ] Add drift detection between project catalog and presensi config.
- [ ] Verify outbox scheduler/retry actually runs.
- [ ] Do not turn camera/GPS evidence into automatic payroll authority.

Acceptance:

- Project presensi tab loads correct project.
- Failed WhatsApp delivery does not lose attendance.

### Phase 6 — UI/UX production hardening

#### PG-600 — Design system consolidation

Files:

- Preserve/refine: `dashboard/src/design-system.css`, `dashboard/tokens.json`
- Reduce cascade across stylesheet imports in `dashboard/src/main.tsx`.

Tasks:

- [ ] Define token ownership.
- [ ] Consolidate overlapping selectors.
- [ ] Remove legacy styles only after screenshot parity.
- [ ] Preserve light/dark contrast.
- [ ] Standardize form, table, card, dialog, toast, empty/error/loading states.

Acceptance:

- CSS order change does not alter unrelated features.
- No accidental global override.

#### PG-610 — Responsive matrix

Required viewports:

- 320×568;
- 375×812;
- 390×844;
- 768×1024;
- 900×1440;
- 1366×768;
- 1440×900;
- 1920×1080.

Tasks:

- [ ] Verify all seven routes.
- [ ] No page-level horizontal overflow.
- [ ] Tables become labeled cards or controlled internal scroll.
- [ ] Modal usable with keyboard/touch and virtual keyboard.
- [ ] Chart gestures do not block page navigation.
- [ ] Breadcrumb/context remains visible.

Acceptance:

- Visual evidence captured for every route at mobile/tablet/desktop.

#### PG-620 — Accessibility

Tasks:

- [ ] WCAG 2.2 AA contrast.
- [ ] axe serious/critical = 0.
- [ ] Keyboard-only complete workflows.
- [ ] Visible focus.
- [ ] Dialog focus trap/return.
- [ ] Labels, descriptions, error association, live regions.
- [ ] 200% zoom.
- [ ] Reduced motion.
- [ ] Touch targets at least 44×44 where applicable.

Acceptance:

- Current light surface contrast failure fixed.
- Candlestick action usable without mouse/right-click.

### Phase 7 — Test contract dan quality gates

#### PG-700 — Unit dan selector tests

- [ ] Ledger effective-state calculations.
- [ ] Profitability.
- [ ] Debt double-entry and aging.
- [ ] Wallet health.
- [ ] Office classification.
- [ ] Project lifecycle/candle mapping.
- [ ] Status mapping including cancelled.
- [ ] Report totals.

#### PG-710 — API contract tests

- [ ] Auth/role/CSRF.
- [ ] Payload validation.
- [ ] Idempotency/concurrency.
- [ ] Create/read/correct/reverse transaction.
- [ ] Debt lifecycle.
- [ ] Project lifecycle.
- [ ] Capability false hides UI; capability true proves route.

#### PG-720 — PostgreSQL integration tests

- [ ] All migrations from empty DB.
- [ ] Upgrade from production-like schema snapshot.
- [ ] Constraints/triggers/indexes.
- [ ] Transaction/debt rollback boundaries.
- [ ] Outbox and reconciliation.
- [ ] Concurrent duplicate submissions.

#### PG-730 — Authenticated browser E2E

Browsers:

- Chromium;
- Firefox;
- WebKit.

Required scenarios:

- [ ] Login/logout/session renewal.
- [ ] CSRF positive and negative.
- [ ] Seven menu presence contract.
- [ ] Flow A Proyek Pak Rahmat.
- [ ] Flow B Pinjaman.
- [ ] Flow C WhatsApp-to-Dashboard using isolated environment/mocked provider boundary.
- [ ] Flow D Office.
- [ ] Flow E PDF.
- [ ] Refresh/deep-link/new session.
- [ ] No dead buttons.
- [ ] Feature registry parity.

#### PG-740 — Visual regression

- [ ] Baseline screenshots per route/theme/viewport.
- [ ] Component snapshots are not enough; authenticated route screenshots required.
- [ ] Pixel/semantic threshold reviewed.
- [ ] Explicit approval for intentional visual changes.

#### PG-750 — Security tests

- [ ] `pip-audit` independent job.
- [ ] Bandit independent job.
- [ ] Ruff independent job.
- [ ] `npm audit --omit=dev`.
- [ ] PHP lint.
- [ ] secret scan.
- [ ] SBOM.
- [ ] container vulnerability scan.
- [ ] proxy allowlist/path traversal/content-type/body-size tests.
- [ ] DAST authenticated staging baseline.

Acceptance:

- Satu visual failure tidak boleh menyebabkan security jobs skipped.

#### PG-760 — Performance tests dan numeric SLO

SLO minimum dibekukan **sebelum** candidate diukur; threshold tidak boleh dilonggarkan agar candidate lulus:

- LCP p75 `<= 2.5s` pada agreed mobile profile;
- INP p75 `<= 200ms`;
- CLS p75 `<= 0.1`;
- authenticated read API p95 `<= 1.5s`;
- financial write API p95 `<= 3s`, tidak termasuk OCR/provider processing;
- server error rate `< 1%` selama 15 menit;
- Sheets export lag `<= 5 menit`;
- oldest unprocessed durable inbox `<= 2 menit` pada provider normal;
- restore RTO `<= 4 jam`;
- backup RPO: owner-approved numeric target wajib; jika tidak disetujui, 24 jam **tidak boleh diasumsikan cukup**.

Budgets/test tambahan:

- [ ] bundle size;
- [ ] cold start;
- [ ] query count/plan;
- [ ] 100+ project chart rendering;
- [ ] concurrent transaction writes;
- [ ] PDF generation time/memory.

Acceptance:

- SLO/budget tersimpan di versioned config dan CI fail bila terlampaui.
- Synthetic threshold breach mengirim verified alert ke actual destination.
- Nilai threshold tidak diubah setelah hasil candidate terlihat kecuali requirement resmi berubah.

### Phase 8 — Backup, restore, monitoring, reliability

#### PG-800 — Automated backup dan canonical cutoff

- [ ] Schedule encrypted backup.
- [ ] PostgreSQL, Sheets backup/export, Presensi tree, configs inventory.
- [ ] Catat PostgreSQL transaction cutoff/LSN pada setiap backup.
- [ ] Verifikasi consistency backup independen dari asynchronous Sheets export.
- [ ] Aktifkan dan uji PITR bila approved RPO lebih kecil dari dump interval.
- [ ] Offsite upload.
- [ ] Downloaded-byte/hash/decrypt/tar readback.
- [ ] Retention policy.
- [ ] Failure alert.
- [ ] Document owner-approved numeric RPO.

#### PG-810 — Full restore drill

- [ ] Restore PostgreSQL/PITR ke disposable environment pada recorded cutoff.
- [ ] Restore Sheets export ke disposable copy.
- [ ] Restore Presensi tree ke disposable path.
- [ ] Start application against restored stack.
- [ ] Jalankan canonical balance, debt, project, document-reference, dan report-dataset-hash checks.
- [ ] Login dan verify historical project/transaction/debt/report.
- [ ] Measure RTO dan bandingkan dengan `<= 4 jam`.

Acceptance:

- Restored application mereproduksi canonical totals pada recorded cutoff.
- Tidak ada backup diterima hanya karena `pg_restore` exit `0`.
- Tool success tanpa application readback tidak cukup.

#### PG-820 — Monitoring

Threshold harus mempunyai owner-approved rationale atau measured healthy baseline **sebelum candidate diukur**. Default konservatif berikut berlaku sampai evidence sebelum-candidate menyetujui nilai yang lebih ketat atau berbeda:

- [ ] Koyeb health/release: alert setelah `3` probe gagal berturut-turut dalam window `5 menit`; recovery juga diverifikasi.
- [ ] Rumahweb admin/absen release manifest: alert pada satu mismatch SHA/digest atau `2` probe unavailable berturut-turut dalam `5 menit`.
- [ ] Authenticated route/write-path canary: alert pada satu failure; canary interval dan test namespace versioned.
- [ ] Durable inbox: oldest unprocessed `<= 2 menit` pada provider normal; alert bila count bertambah pada dua evaluation window berturut-turut.
- [ ] Review queue: pre-cutover unresolved wajib `0` kecuali owner-approved exclusion/quarantine; post-cutover alert bila item unresolved berumur `>24 jam` atau count bertambah selama `2` window harian.
- [ ] Sheets export lag `<= 5 menit` dan drift `0` pada canonical cutoff; satu nonzero drift memicu alert.
- [ ] Error rate `< 1%/15 menit` dan API latency mengikuti numeric SLO.
- [ ] Backup freshness tidak boleh melebihi approved RPO; satu miss memicu alert.
- [ ] WuzAPI connectivity: probe setiap `1 menit`; alert setelah `3` kegagalan berturut-turut atau outage `>=5 menit`; recovery event wajib diterima.
- [ ] Presensi outbox: alert bila `pending/leased/unknown > 0` berumur `>5 menit` atau failed item tidak berhasil diretry dalam `15 menit`.
- [ ] Alert destination, evaluation window, severity, owner, dedup, escalation, dan remediation runbook versioned.

Acceptance:

- Current 76 review items sudah mempunyai disposition sebelum cutover.
- Setiap threshold memiliki pre-candidate rationale/baseline, approver, version, dan tanggal freeze.
- Synthetic breach **setiap** signal di atas menghasilkan alert yang dibaca kembali dari actual destination; synthetic recovery menghasilkan resolved event.
- Monitoring config versioned; threshold tidak disetel longgar setelah melihat candidate.

### Phase 9 — CI, release provenance, dan expand/deploy readiness

#### PG-900 — CI required checks

- [ ] Pisahkan backend tests, browser E2E, visual, security, frontend, PostgreSQL, PHP, container, performance, accessibility.
- [ ] Branch protection mewajibkan seluruh required checks.
- [ ] Koyeb auto-deploy dari branch merah dimatikan atau digate melalui promotion workflow.
- [ ] Tidak ada production promotion sebelum seluruh checks hijau.
- [ ] Read back GitHub branch-protection/required-check settings dan Koyeb deployment settings; screenshot/command success saja tidak cukup.

#### PG-910 — Immutable release artifact

Files:

- Create: `release-manifest.json` during build.

Manifest minimal:

- full Git SHA;
- parent SHA;
- build timestamp;
- frontend asset hashes;
- backend image digest;
- schema version dan compatibility range;
- feature manifest version;
- canonical metric/report version;
- target environment;
- CI run URL/ID.

Acceptance:

- Manifest yang sama dapat dibaca dari GitHub artifact, Koyeb, `/admin/release.json`, dan `/absen/release.json`.
- Image/artifact dibangun sekali; staging dan production mempromosikan bytes/digest sama, bukan rebuild.

#### PG-920 — Staging release candidate

- [ ] Deploy exact immutable backend image.
- [ ] Deploy exact Rumahweb artifact ke isolated staging path/origin.
- [ ] Run one-shot versioned migrations dengan lock.
- [ ] Verify fresh-zero bootstrap, archive isolation, dan no-import guard.
- [ ] Run full authenticated E2E seluruh write/read path.
- [ ] Run security/performance/accessibility.
- [ ] Run backup/restore/PITR drill.
- [ ] Freeze release candidate SHA/digest setelah seluruh gates lulus.

#### PG-930 — Production expand dan dormant canonical-aware deployment

Urutan wajib:

- [ ] Apply backward-compatible **expand migrations** dengan dedicated one-shot job/lock.
- [ ] Deploy exact canonical-aware Koyeb image dengan PostgreSQL business read/write **belum diaktifkan**.
- [ ] Deploy/activate backward-compatible Rumahweb proxy/session layer; UI baru tetap capability-gated/dormant.
- [ ] Verify release SHA/digest, schema compatibility, auth trust, dormant route registration, health, dan legacy behavior.
- [ ] Freeze daftar rollback artifact: artifact lama hanya eligible sebelum canonical authority activation.

Acceptance:

- Belum ada process yang menulis dua authority.
- Old production workflow tetap berjalan sampai cutover window.
- Dormant canonical routes tidak dapat diaktifkan client-side tanpa server capability.

### Phase 10 — Production authority activation dan go-live

#### PG-1000 — Pre-activation gate

- [ ] Production backup/PITR checkpoint + offsite readback.
- [ ] Maintenance/cutover window defined.
- [ ] Rollback owner and exact commands verified.
- [ ] Historical Sheets archive dibekukan dan terbukti tidak menjadi production input.
- [ ] Fresh-zero readback: zero canonical transaction/debt/project-finance rows dan zero balances.
- [ ] Current feature/authority manifest captured.
- [ ] New release manifest signed/hashed.
- [ ] Numeric RPO/RTO dan SLO disetujui.
- [ ] No unresolved task dalam plan ini.

#### PG-1010 — Atomic database authority activation

Urutan wajib:

- [ ] Stop/fence seluruh legacy Sheets primary writers di Dashboard, WhatsApp, worker, cron, dan manual integration.
- [ ] Freeze immutable Sheets archive snapshot/hash dan tandai `historical_import=false`.
- [ ] Verify PostgreSQL fresh-zero bootstrap; jangan jalankan historical import.
- [ ] Atomically switch canonical reads/writes ke PostgreSQL pada canonical-aware release yang sudah deployed.
- [ ] Enable protected one-way Sheets export outbox.
- [ ] Enable transaction/debt/office/project capabilities hanya setelah authority readback hijau.
- [ ] Verify WhatsApp dan Dashboard membaca/menulis finance core sama.
- [ ] Observe duplicate, error, drift, latency, dan export lag selama bounded activation window.

Acceptance:

- Tidak ada deployed process yang dapat menulis kedua authority sebagai primary.
- Setelah canonical commit pertama, rollback tidak pernah menghidupkan direct Sheets primary writes.
- Hanya canonical-aware image/artifact eligible untuk rollback setelah activation.

Rollback/stop conditions:

- canonical write/readback failure;
- reconciliation drift;
- wallet/project/reference mismatch;
- duplicate side effect;
- authentication/actor failure;
- SLO breach.

Rollback setelah canonical activation berarti rollback aplikasi ke **canonical-aware previous artifact**, PostgreSQL tetap authority, pending Sheets export direplay. Destructive down migration dan kembali ke Sheets-primary dilarang.

#### PG-1020 — Scoped production write-path acceptance dan frontend activation

Production canary policy:

- Gunakan reserved `test_namespace`/`is_acceptance_test=true` yang secara schema/query diwajibkan keluar dari business totals, default reports, invoice allocation, payroll, dan normal project portfolio.
- Canary tetap mempunyai audit ID; cleanup memakai reversal/closure sehingga effective financial impact `0`.
- Test namespace bukan proyek/transaksi bisnis palsu dan tidak boleh terlihat pada default admin view.

Required authenticated production scenarios:

- [ ] Generate suite dari `featureManifest`/action registry; **setiap enabled registered mutation** wajib dieksekusi melalui authorization, canonical write, authoritative readback, audit, projection/export, dan effective-zero cleanup. Handpicked scenario tidak boleh menggantikan registry coverage.
- [ ] Login, session renewal, logout, anonymous denial, actor/role attribution.
- [ ] Create/readback, edit, allowed status transitions, cancel/complete semantics, dan archive satu tagged canary project.
- [ ] Create, correct, dan reverse satu tagged project transaction.
- [ ] Create, partial repay, full repay/reverse, correct, dan archive satu tagged inter-wallet project debt.
- [ ] Create, correct, dan reverse satu tagged office transaction.
- [ ] Commit satu tagged WhatsApp-origin canonical transaction melalui allowlisted acceptance identity; verify durable inbox, dedup, correction/reversal, Dashboard readback, dan export.
- [ ] Exercise setiap capability mutation lain yang terdaftar pada release final; registry coverage wajib `100%`, bukan daftar statis yang dapat tertinggal.
- [ ] Generate/parse PDF tagged scope; compare canonical dataset hash.
- [ ] Verify wallet/project/debt/office/report/audit/Sheets-export effects dan effective impact `0` setelah cleanup.
- [ ] Setelah seluruh registry-derived write paths lulus, activate exact staged frontend route/capabilities secara atomik.
- [ ] Verify `/admin/release.json`, `/absen/release.json`, dan Koyeb manifest exact match.

Acceptance:

- Zero enabled registered mutation tanpa production execution evidence.
- Setiap mutation membuktikan actor/role, idempotency, canonical readback, audit ID, dependent projections, export behavior, dan cleanup/effective impact `0`.
- Capability yang tidak aman diuji tidak boleh enabled; hidden/disabled state dan alasannya harus cocok dengan feature registry.

#### PG-1030 — Full post-deploy product acceptance

- [ ] HTTP/TLS/assets/hash dan exact SHA/digest parity.
- [ ] Tepat tujuh menu pada desktop/mobile.
- [ ] Semua registered controls enabled/hidden sesuai capability dan tidak ada dead control.
- [ ] Project Candles production visible, year filter berfungsi, candle membuka exact UUID.
- [ ] Existing business project, transaction, debt, office, wallet, document, presensi, report terbaca benar.
- [ ] Authenticated deep links, refresh, new session.
- [ ] No console/page/network errors.
- [ ] Chromium/Firefox/WebKit dan required viewport matrix.
- [ ] WuzAPI inbox/outbox serta canonical query.
- [ ] Sheets one-way export lag/drift memenuhi SLO.
- [ ] Monitoring dan alert readback hijau.

#### PG-1040 — Authority-safe rollback drill

- [ ] Sebelum activation, exercise full previous-artifact rollback.
- [ ] Setelah canonical activation, exercise Rumahweb rollback ke previous **canonical-aware** artifact.
- [ ] Exercise Koyeb previous **canonical-aware** image promotion.
- [ ] Verify PostgreSQL tetap authority, no direct Sheets writes resume, pending exports replay, dan forward schema compatible.
- [ ] Re-run authenticated write/read smoke dan canonical oracle checks setelah rollback.
- [ ] Record measured recovery time dan buktikan RTO.

#### PG-1050 — Contract/observation window

- [ ] Pertahankan expanded schema dan legacy code fenced selama observation window terukur.
- [ ] Monitor errors, drift, export lag, backlog, auth, SLO, dan business reconciliation.
- [ ] Contract/drop legacy paths hanya setelah observation acceptance hijau dan rollback tidak memerlukannya.
- [ ] Tidak ada old Sheets-primary artifact tersisa sebagai eligible production rollback.

### Phase 11 — Cleanup dan operational handoff

#### PG-1100 — Remove legacy only after parity

- [ ] Remove/archive parallel project list/detail implementations.
- [ ] Remove dead demo/fallback routes from production bundle.
- [ ] Remove duplicate CSS only after visual regression.
- [ ] Remove direct Sheets primary write paths only after authority cutover proven.
- [ ] Keep migration/export tools and audit records.

#### PG-1110 — Runbooks

- [ ] Architecture and authority.
- [ ] Admin user flow.
- [ ] Transaction correction/reversal.
- [ ] Debt and repayment.
- [ ] Review queue.
- [ ] Backup/restore.
- [ ] Deploy/rollback.
- [ ] Incident response.
- [ ] Canva quotation and negotiation boundary.

#### PG-1120 — Evidence package

- [ ] Commit SHA and release manifest.
- [ ] CI links/results.
- [ ] Migration/reconciliation report.
- [ ] Test results.
- [ ] Browser screenshots/video.
- [ ] Accessibility/performance/security reports.
- [ ] Backup/restore evidence.
- [ ] Deploy/rollback logs.
- [ ] Post-deploy verification JSON.
- [ ] Cloud backup with downloaded-byte and integrity readback.

---

## 9. Acceptance matrix final

### Architecture

- [ ] Satu canonical Project Domain.
- [ ] Satu canonical Financial Ledger.
- [ ] PostgreSQL authority; Sheets backup/export.
- [ ] WhatsApp/Dashboard memakai service sama.
- [ ] Presensi authority dan boundary jelas.

### Dashboard product

- [ ] Tepat tujuh menu utama.
- [ ] Setiap menu mempunyai responsibility berbeda.
- [ ] Tidak ada duplicate canonical forms.
- [ ] Tidak ada tombol mati.
- [ ] Tidak ada fitur demo masquerading as production.

### Project

- [ ] Year selector production.
- [ ] Candlestick production.
- [ ] Add/edit/status/archive.
- [ ] Detail UUID.
- [ ] Transaction lifecycle lengkap.
- [ ] Project borrowing lengkap.
- [ ] Profitability benar.
- [ ] Presensi/dokumen/audit benar.

### Financial integrity

- [ ] Opening balance + effective postings = available balance pada setiap wallet/cutoff.
- [ ] Balance adjustment auditable; tidak ada silent overwrite.
- [ ] Office classification benar.
- [ ] Debt balanced, netral terhadap P&L dan group cash.
- [ ] Wallet totals reconcile ke canonical metric oracle.
- [ ] Correction/reversal immutable, no cycle/double reversal.
- [ ] No hard delete.
- [ ] Idempotency/concurrency/crash-window proven.
- [ ] Fresh-zero canonical count, amount, debt, project-finance, dan balance terbukti nol sebelum canary.
- [ ] Historical Sheets archive tidak berkontribusi ke canonical totals atau Dashboard.
- [ ] Tidak ada forbidden Sheets business read/write.

### Quality

- [ ] Unit/contract/integration/E2E hijau.
- [ ] Chromium/Firefox/WebKit hijau.
- [ ] Semua viewport hijau.
- [ ] Accessibility AA hijau.
- [ ] Performance budgets hijau.
- [ ] Security gates hijau.

### Operations

- [ ] Automated backup proven.
- [ ] Full restore drill proven.
- [ ] Monitoring thresholds active.
- [ ] CI blocks deploy.
- [ ] Exact release provenance on all targets.
- [ ] Atomic deploy and rollback proven.
- [ ] Authenticated post-deploy acceptance proven.

---

## 10. Definition of Done — satu-satunya syarat status `OK`

Release hanya boleh diberi status **OK / PRODUCTION-GRADE** jika seluruh kondisi berikut benar sekaligus:

1. Semua checkbox wajib dalam plan ini selesai dan mempunyai evidence.
2. Candidate terbukti descendant exact baseline `0ee6a95...`; seluruh diff terlacak ke task ID.
3. Tidak ada defect Critical/High terbuka.
4. Tidak ada medium defect yang merusak workflow, data, accessibility, atau operasi.
5. Required CI commit final seluruhnya hijau; branch protection dan promotion settings dibaca kembali.
6. Commit/image/artifact final immutable; manifest SHA/digest sama di GitHub, Koyeb, Rumahweb Admin, dan Rumahweb Presensi.
7. Opening balance, adjustments, effective postings, debt, project, document/evidence references, dan canonical metrics lulus oracle.
8. Seluruh 76 review items mempunyai row-level disposition; tidak ada unexplained row/amount/balance/reference drift.
9. PostgreSQL menjadi satu-satunya authority; semua legacy Sheets business call-sites retired; Sheets hanya protected one-way export/backup.
10. Auth actor trust, role, CSRF, signed assertion, rotation, dan direct-origin restriction terbukti fail-closed.
11. Flow A–E lulus di staging dan seluruh production write paths lulus dalam reserved test namespace dengan effective impact `0`.
12. Tepat tujuh menu production tampil dan berfungsi setelah login.
13. Candlestick dan year selector terlihat pada route Proyek production serta memakai lifecycle events kanonis.
14. Transaction create/read/correct/reverse terbukti persistence, actor audit, dan authoritative readback.
15. Project debt create/repay/correct/reverse menghasilkan balanced postings dan konsisten di Proyek/Dompet/Hutang.
16. Office tidak tercemar transaksi proyek yatim.
17. PDF parsed totals cocok dengan independent canonical report oracle dan dataset hash.
18. Numeric SLO, accessibility, security, responsive/browser matrix, dan performance gates hijau.
19. Backup terbaru mempunyai LSN/cutoff, dapat diunduh, didekripsi, direstore/PITR, lalu dibaca aplikasi dengan canonical totals sama.
20. Authority-safe rollback Koyeb/Rumahweb teruji tanpa menghidupkan Sheets-primary kembali.
21. Monitoring threshold dan verified alert delivery aktif.
22. Observation window lulus; tidak ada old Sheets-primary artifact eligible untuk rollback.
23. Evidence package tersimpan lokal dan offsite dengan integrity readback.

Hal berikut **tidak cukup** untuk menyatakan selesai:

- file/komponen sudah ada;
- tombol terlihat;
- build berhasil;
- unit test hijau;
- HTTP 200;
- deployment command exit 0;
- backend SHA cocok tetapi frontend tidak diketahui;
- fitur bekerja pada fixture/demo;
- angka terlihat tanpa rekonsiliasi;
- backup dibuat tetapi belum direstore;
- route public terbuka tetapi flow authenticated belum diuji.

---

## 11. Urutan eksekusi yang dikomit

```text
Exact baseline guard + dependency readiness
        ↓
Feature contract + authority/auth/metric ADR
        ↓
Canonical schema + one-shot migration contract
        ↓
Historical manifest/backfill + disposition 76 review rows
        ↓
Canonical transaction/debt/report services
        ↓
Retire seluruh Sheets business call-sites
        ↓
WhatsApp + Dashboard memakai finance core sama
        ↓
Satu shell + tujuh menu + registered controls
        ↓
Satu Project workspace + Project Candles
        ↓
Transaction correction/reversal + project borrowing
        ↓
Office/Wallet/Debt/Reports completion
        ↓
UI/UX + accessibility + responsive + numeric SLO
        ↓
Full test + security + backup/restore/PITR
        ↓
Build-once immutable staging release
        ↓
Production expand migration
        ↓
Deploy canonical-aware backend/proxy dalam mode dormant
        ↓
Fence legacy writers + final zero-drift reconciliation
        ↓
Atomically activate PostgreSQL authority + Sheets one-way export
        ↓
Scoped production write-path acceptance
        ↓
Activate exact frontend artifact
        ↓
Full product/browser acceptance
        ↓
Authority-safe rollback drill + observation window
        ↓
Evidence package
        ↓
OK
```

Keputusan tidak boleh dibuka ulang tanpa bukti baru:

- PostgreSQL target authority.
- Sheets target backup/export.
- Project UUID canonical.
- Ledger correction/reversal, bukan destructive delete.
- Satu project implementation.
- Tujuh menu dengan action ownership berbeda.
- CI hijau sebelum promotion.
- Outcome browser production sebagai acceptance akhir.
