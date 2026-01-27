"""
constants.py - Sheet Constants and Configuration

Contains:
- SHEET_HEADERS: Column header names
- Column indices (COL_*) for gspread operations
- Dashboard and system sheet names
- Budget configuration
- Commands: Bot command aliases
- Timeouts: Time-related constants
- KNOWN_COMPANY_NAMES: Hardcoded list of companies/wallets
- PROJECT_STOPWORDS: Words forbidden from being project names
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ===================== SPREADSHEET CONFIG =====================

# Column order: No, Tanggal, Company, Keterangan, Jumlah, Tipe, Oleh, Source, Kategori, Nama Projek, MessageID
SHEET_HEADERS = ['No', 'Tanggal', 'Company', 'Keterangan', 'Jumlah', 'Tipe', 'Oleh', 'Source', 'Kategori', 'Nama Projek', 'MessageID']

# Column indices (1-based for gspread)
COL_NO = 1
COL_TANGGAL = 2
COL_COMPANY = 3
COL_KETERANGAN = 4
COL_JUMLAH = 5
COL_TIPE = 6
COL_OLEH = 7
COL_SOURCE = 8
COL_KATEGORI = 9
COL_NAMA_PROJEK = 10
COL_MESSAGE_ID = 11

# Dashboard configuration
DASHBOARD_SHEET_NAME = "Dashboard"
SYSTEM_SHEETS = {'Config', 'Template', 'Settings', 'Master', DASHBOARD_SHEET_NAME, 'Data_Agregat'}

# Budget configuration
DEFAULT_BUDGET = int(os.getenv('DEFAULT_PROJECT_BUDGET', '10000000'))
BUDGET_WARNING_PERCENT = 80

# Google Sheets configuration
SPREADSHEET_ID = os.getenv('GOOGLE_SHEETS_ID')
CREDENTIALS_FILE = os.getenv('CREDENTIALS_FILE', 'credentials.json')

# Scopes for Google API
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# ===================== MAGIC STRINGS (YAGNI Config) =====================

# Daftar nama perusahaan/dompet yang sudah pasti (Hardcoded for efficiency)
# Digunakan untuk mencegah AI menganggap nama ini sebagai "Nama Projek"
KNOWN_COMPANY_NAMES = {
    # Companies
    "holla", "hojja", "holja",
    "texturin", "texturin-bali", "texturin bali",
    "texturin-surabaya", "texturin surabaya", "texturin sby",
    "kantor", "umum",
    
    # Wallets (Agar "Isi Dompet Evan" tidak dianggap Projek "Dompet Evan")
    "dompet evan", "dompet holja", "dompet holla",
    "dompet texturin", "dompet texturin sby"
}

# Daftar kata yang DILARANG menjadi Nama Projek
# Jika AI mendeteksi kata ini sebagai projek, akan diabaikan/dihapus
PROJECT_STOPWORDS = {
    # Kata Kerja Transaksi
    "biaya", "bayar", "beli", "transfer", "kirim", "isi", "topup",
    "terima", "lunasin", "ganti", "revisi", "ubah", "koreksi", 
    "update", "cancel", "batal", "hapus", "catat", "input", "simpan",
    
    # Istilah Keuangan
    "fee", "gaji", "pajak", "kas", "uang", "lunas", "dp", "pelunasan",
    "cicil", "cicilan", "admin", "tunai", "cash", "debt", "hutang",
    "saldo", "wallet", "dompet", "rekening", "atm", "bank",
    
    # Kebutuhan Umum (Bukan nama bangunan/projek spesifik)
    "makan", "minum", "jamu", "snack", "konsumsi",
    "bensin", "bbm", "parkir", "tol", "toll", "ongkir",
    "sewa", "listrik", "air", "wifi", "pulsa", "internet",
    "kebersihan", "keamanan", "transport",
    
    # Material Umum (Agar tidak muncul "Projek Semen")
    "semen", "pasir", "cat", "bata", "kayu", "paku", 
    "besi", "keramik", "gerinda", "bor", "gergaji", "meteran",
    
    # Kata Sambung
    "dari", "ke", "untuk", "via", "dengan", "dan", "atau", 
    "pembayaran", "transaksi", "project", "projek"
}


# ===================== TIMEOUTS =====================

class Timeouts:
    """Time-related constants in seconds."""
    PENDING_TRANSACTION = 15 * 60  # 15 minutes - pending selection TTL
    RATE_LIMIT_WINDOW = 60         # 1 minute - rate limit window
    DEDUP_WINDOW = 5 * 60          # 5 minutes - message deduplication
    REQUEST_TIMEOUT = 10           # API request timeout
    BOT_REFS_MAX = 1000            # Max bot message refs to cache


# ===================== COMMANDS =====================

class Commands:
    """
    Bot command aliases - all lowercase for matching.
    """
    
    # Bot start/help
    START_SLASH = ['/start']
    START_PRIVATE = ['start', 'mulai', 'hi', 'halo']
    START = START_SLASH + START_PRIVATE
    
    HELP_SLASH = ['/help', '/bantuan']
    HELP_PRIVATE = ['help', 'bantuan']
    HELP = HELP_SLASH + HELP_PRIVATE
    
    # Status/dashboard commands
    STATUS_SLASH = ['/status', '/cek']
    STATUS_PRIVATE = ['status', 'cek']
    STATUS = STATUS_SLASH + STATUS_PRIVATE
    
    SALDO_SLASH = ['/saldo']
    SALDO_PRIVATE = ['saldo']
    SALDO = SALDO_SLASH + SALDO_PRIVATE
    
    LIST_SLASH = ['/list']
    LIST_PRIVATE = ['list']
    LIST = LIST_SLASH + LIST_PRIVATE
    
    # Reporting
    LAPORAN_SLASH = ['/laporan']
    LAPORAN_PRIVATE = ['laporan']
    LAPORAN = LAPORAN_SLASH + LAPORAN_PRIVATE
    
    LAPORAN_30_SLASH = ['/laporan30']
    LAPORAN_30_PRIVATE = ['laporan30']
    LAPORAN_30 = LAPORAN_30_SLASH + LAPORAN_30_PRIVATE
    
    # Transaction/wallet commands
    DOMPET_SLASH = ['/dompet', '/company', '/project']
    DOMPET_PRIVATE = ['dompet', 'company', 'project']
    DOMPET = DOMPET_SLASH + DOMPET_PRIVATE
    
    KATEGORI_SLASH = ['/kategori']
    KATEGORI_PRIVATE = ['kategori']
    KATEGORI = KATEGORI_SLASH + KATEGORI_PRIVATE
    
    # AI query prefixes (check with startswith)
    TANYA_SLASH = ['/tanya ']
    TANYA_PRIVATE = ['tanya ']
    TANYA_PREFIXES = TANYA_SLASH + TANYA_PRIVATE
    
    # Export prefixes
    EXPORT_PDF_SLASH = ['/exportpdf']
    EXPORT_PDF_PRIVATE = ['exportpdf']
    EXPORT_PDF_PREFIXES = EXPORT_PDF_SLASH + EXPORT_PDF_PRIVATE
    
    # Cancel/revision - ONLY slash for safety
    CANCEL = ['/cancel', 'batal', 'cancel']
    REVISION_PREFIXES = ['/revisi']  # Slash only for revision
    
    # Link command
    LINK_SLASH = ['/link']
    LINK_PRIVATE = ['link']
    LINK = LINK_SLASH + LINK_PRIVATE


# ===================== GROUP TRIGGERS =====================

GROUP_TRIGGERS = ["+catat", "+bot", "+input", "/catat"]


# For testing
if __name__ == '__main__':
    print("Constants Configuration Test")
    print(f"Sheet Headers: {SHEET_HEADERS}")
    print(f"Known Companies Count: {len(KNOWN_COMPANY_NAMES)}")
    print(f"Project Stopwords Count: {len(PROJECT_STOPWORDS)}")
    print(f"Default Budget: {DEFAULT_BUDGET}")