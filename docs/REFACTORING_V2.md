# Bot Keuangan v2.0 - Cost Accounting Refactoring

## 📋 Overview

Refactoring ini mengimplementasikan "Cost Accounting" yang memisahkan:

- **Operasional (Fixed Costs)**: Gaji, Listrik, Air, Konsumsi, Peralatan
- **Project (Variable Costs)**: Material, Tenaga kerja projek, Transport ke site

## 🏗️ Struktur Database (Google Sheets)

### Tipe A: Sheet Dompet (Split Layout)

Target Sheets: `CV HB (101)`, `TX SBY(216)`, `TX BALI(087)`

```
PEMASUKAN (Kiri: A-I)          | PENGELUARAN (Kanan: J-R)
-------------------------------|--------------------------------
No|Waktu|Tanggal|Jml|Proj|Ket| | No|Waktu|Tanggal|Jml|Proj|Ket|
  |     |       |   |    |Oleh|  |  |     |       |   |    |Oleh
  |     |       |   |    |Src|   |  |     |       |   |    |Src
  |     |       |   |    |MsgID| |  |     |       |   |    |MsgID
```

### Tipe B: Sheet Operasional (Single Table)

Target Sheet: `Operasional Kantor`

```
No|Tanggal|JUMLAH|KETERANGAN|Oleh|Source|Kategori|MessageID
--|-------|------|----------|----|----- |--------|----------
  |       |      |...[Sumber: CV HB]|   |   |Gaji    |
```

## 🔧 Perubahan Utama

### 1. `utils/groq_analyzer.py` (NEW v2.0)

- ✅ Tambah intent `TRANSFER_FUNDS` untuk transfer antar dompet
- ✅ Tambah `category_scope` (OPERATIONAL/PROJECT/UNKNOWN)
- ✅ Penguatan "Negative Constraint" untuk membedakan:
  - Rencana (future tense) vs Kejadian (past tense)
  - Perintah ke manusia vs Laporan ke bot
- ✅ Amount pattern detection untuk menghindari false positive
- ✅ Safety overrides rule-based

### 2. `handlers/smart_handler.py` (v2.0)

- ✅ Integrasi amount pattern detection dari groq_analyzer
- ✅ Handle TRANSFER_FUNDS intent
- ✅ Pass `category_scope` ke main.py
- ✅ Fixed missing import `update_transaction_amount`

### 3. `main.py` (Enhanced)

- ✅ `detect_transaction_context()` sekarang menerima `category_scope` dari AI
- ✅ Word boundary matching untuk keyword detection lebih akurat
- ✅ Integrasi dengan 4-tuple return dari layer_integration
- ✅ Fixed selection prompt: 1-4 (bukan 1-5)
- ✅ `layer_category_scope` tersimpan di pending state

### 4. `layer_integration.py` (v2.0)

- ✅ Return 4-tuple: `(action, response, intent, extra_data)`
- ✅ `extra_data` berisi `category_scope`, `extracted_data`, `layer_response`

### 5. `services/project_service.py` (Enhanced)

- ✅ Word boundary matching untuk `is_operational_keyword()`
- ✅ Lebih akurat mendeteksi keyword operasional

### 6. `sheets_helper.py` (Already Implemented)

- ✅ `append_project_transaction()` - Split Layout
- ✅ `append_operational_transaction()` - dengan [Sumber: X] tag
- ✅ `get_wallet_balances()` - Virtual Balance formula

### 7. `utils/formatters.py` (Fixed)

- ✅ Selection prompt: 1-4 (bukan 1-5)

## 📊 Flow Diagram

```
User Input
    │
    ▼
┌───────────────────────┐
│  SmartHandler v2.0    │
│  - Amount pattern?    │
│  - Past/Future tense? │
│  - Financial keyword? │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  GroqContextAnalyzer  │
│  - Intent Detection   │
│  - category_scope     │
│  - Negative Constraints│
└───────────┬───────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│        detect_transaction_context       │
│  Priority 1: AI says OPERATIONAL → OPS  │
│  Priority 2: Valid Project Name → PROJ  │
│  Priority 3: Keywords + No Project → OPS│
│  Default: PROJECT                       │
└───────────────────┬─────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌───────────────┐       ┌───────────────────┐
│ MODE: PROJECT │       │ MODE: OPERATIONAL │
│               │       │                   │
│ Ask Company?  │       │ Ask Wallet?       │
│ (1-4)         │       │ (1-3)             │
│               │       │                   │
│ Save to       │       │ Save to           │
│ Dompet Sheet  │       │ Operasional Ktr   │
│ (Split Layout)│       │ with [Sumber: X]  │
└───────────────┘       └───────────────────┘
```

## 📈 Rumus Virtual Balance

```
Real Balance (CV HB) =
    (Total Pemasukan di CV HB - Total Pengeluaran di CV HB)
    - (Total di Operasional Ktr where Keterangan contains '[Sumber: CV HB]')
```

## 🧪 Testing Scenarios

### 1. Chat Biasa vs Transaksi

- ❌ "Nanti siang kita beli nasi padang ya" → IGNORE (future tense)
- ❌ "Tolong beliin kopi dong" → IGNORE (command to human)
- ✅ "Barusan beli bensin 50rb" → RECORD (past tense + amount)
- ✅ "Udah transfer 1jt ke site" → RECORD (past tense + amount)

### 2. Operasional vs Project

- ✅ "Bayar gaji 5jt" → OPERATIONAL (keyword: gaji)
- ✅ "Bayar listrik kantor 500rb" → OPERATIONAL (keyword: listrik)
- ✅ "Beli semen untuk Pak Budi 1jt" → PROJECT (valid project name)
- ✅ "Material proyek Renovasi 2jt" → PROJECT (valid project name)

### 3. Transfer Funds

- ✅ "Topup Gopay 100rb dari BCA" → TRANSFER_FUNDS
- ✅ "Tarik tunai 500rb" → TRANSFER_FUNDS

## 📝 Notes

1. KANTOR expenses sekarang masuk ke Sheet "Operasional Kantor", bukan sebagai company
2. Selection prompt hanya 4 pilihan (HOLLA, HOJJA, TX-Surabaya, TX-Bali)
3. AI layer sekarang lebih konservatif - IGNORE jika ragu di group chat
4. Word boundary matching mencegah false positive (e.g., "beligaji" tidak match "gaji")
