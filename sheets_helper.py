import json
import os
import time
import gspread
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from typing import List, Dict, Optional
from config.constants import COL_NAMA_PROJEK


# Cache sederhana agar tidak boros kuota Google API
_project_cache = {
    'names': set(),
    'last_updated': None
}

def get_existing_projects(force_refresh=False):
    """
    Mengambil set nama projek unik dari Spreadsheet.
    Menggunakan cache memori selama 5 menit.
    """
    global _project_cache
    now = datetime.now()
    
    # Refresh jika cache kosong atau sudah > 5 menit
    if force_refresh or not _project_cache['names'] or \
       (_project_cache['last_updated'] and (now - _project_cache['last_updated']).total_seconds() > 300):
           
        try:
            sh = get_sheet("Data_Agregat") # Atau sheet utama tempat transaksi masuk
            # Ambil semua data kolom Nama Projek (Kolom J = index 10)
            # Asumsi row 1 adalah header
            values = sh.col_values(COL_NAMA_PROJEK)[1:] 
            
            # Bersihkan data: Hapus kosong, hapus strip, lowercase untuk set
            unique_projects = set()
            for v in values:
                clean = v.strip()
                if clean and clean.lower() not in ["-", "bensin", "test", ""]: # Filter sampah
                    unique_projects.add(clean)
            
            _project_cache['names'] = unique_projects
            _project_cache['last_updated'] = now
            print(f"[INFO] Project cache updated: {len(unique_projects)} projects found.")
            
        except Exception as e:
            print(f"[ERROR] Failed to fetch projects: {e}")
            # Return old cache if fail
            
    return _project_cache['names']
    
# ===================== STATE PERSISTENCE (HIDDEN SHEET) =====================
STATE_SHEET_NAME = "_BOT_STATE"

def get_or_create_state_sheet():
    """
    Cari sheet _BOT_STATE. Jika tidak ada, buat baru dan HIDE.
    """
    try:
        sh = get_spreadsheet() # Fungsi ini sudah ada di helper Anda
        
        try:
            # Coba ambil sheetnya
            worksheet = sh.worksheet(STATE_SHEET_NAME)
        except:
            # Jika error (tidak ketemu), buat baru
            worksheet = sh.add_worksheet(title=STATE_SHEET_NAME, rows=10, cols=2)
            # Sembunyikan sheet agar rapi
            worksheet.hide()
            print(f"[INFO] Created hidden state sheet: {STATE_SHEET_NAME}")
            
        return worksheet
    except Exception as e:
        print(f"[ERROR] Failed to get state sheet: {e}")
        return None

def save_state_to_cloud(json_state_string):
    """
    Simpan JSON string ke Cell A1 di sheet tersembunyi.
    """
    try:
        ws = get_or_create_state_sheet()
        if ws:
            # Simpan di cell A1. 
            # Batas karakter cell google sheet ~50.000 chars. Cukup untuk pending tx.
            ws.update_cell(1, 1, json_state_string)
            # Optional: Tambahkan timestamp di B1 biar tau kapan terakhir update
            ws.update_cell(1, 2, str(datetime.now()))
    except Exception as e:
        print(f"[ERROR] Failed to save state to cloud: {e}")

def load_state_from_cloud():
    """
    Ambil JSON string dari Cell A1.
    """
    try:
        ws = get_or_create_state_sheet()
        if ws:
            # Ambil data dari A1
            val = ws.cell(1, 1).value
            if val and val.startswith("{"):
                return val
    except Exception as e:
        print(f"[ERROR] Failed to load state from cloud: {e}")
    return None

# Load environment variables
load_dotenv()

# Import security module
from security import (
    ALLOWED_CATEGORIES,
    validate_category,
    validate_category,
    sanitize_input,
    secure_log,
    mask_sensitive_data,
)
import requests
from services.retry_service import add_to_retry_queue

# Import configuration from centralized config module
from config.wallets import (
    DOMPET_SHEETS,
    DOMPET_COMPANIES,
    SELECTION_OPTIONS,
    get_dompet_for_company,
    get_selection_by_idx,
    get_available_dompets,
    get_dompet_short_name,
    DOMPET_ALIASES,
    DOMPET_SHORT_NAMES,
    # Legacy aliases
    COMPANY_SHEETS,
    FUND_SOURCES,
)

from config.constants import (
    SHEET_HEADERS,
    COL_JUMLAH,
    COL_KETERANGAN,
    COL_MESSAGE_ID,
    COL_NAMA_PROJEK,
    COL_OLEH,
    COL_NO, COL_TANGGAL, COL_COMPANY, COL_TIPE, COL_SOURCE, COL_KATEGORI,
    OPERASIONAL_SHEET_NAME,
    OPERASIONAL_COLS,
    OPERASIONAL_DATA_START,
    OPERASIONAL_HEADER_ROW,
    OPERASIONAL_HEADERS,
    DEFAULT_BUDGET,
    BUDGET_WARNING_PERCENT,
    SPLIT_LAYOUT_DATA_START,
    SPLIT_LAYOUT_TITLE_ROW,
    SPLIT_LAYOUT_HEADER_ROW,
    SPLIT_PEMASUKAN,
    SPLIT_PENGELUARAN,
    SPLIT_PEMASUKAN_HEADERS,
    SPLIT_PENGELUARAN_HEADERS,
    DASHBOARD_SHEET_NAME,
    SYSTEM_SHEETS,
    SPREADSHEET_ID,
    CREDENTIALS_FILE,
    SCOPES
)

import re  # For parsing [Sumber: X] tags

# Global instances
_client = None
_spreadsheet = None

def authenticate():
    """
    Authenticate with Google Sheets API using Service Account.
    
    Supports two methods:
    1. GOOGLE_CREDENTIALS env var (JSON string) - for production/Koyeb
    2. credentials.json file - for local development
    """
    global _client
    
    if _client is not None:
        return _client
    
    creds = None
    
    # Method 1: Try environment variable first (production)
    google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
    if google_creds_json:
        try:
            creds_dict = json.loads(google_creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            secure_log("INFO", "Authenticated via GOOGLE_CREDENTIALS env var")
        except Exception as e:
            secure_log("ERROR", f"Failed to parse GOOGLE_CREDENTIALS: {type(e).__name__}")
    
    # Method 2: Try credentials file (local development)
    if not creds and os.path.exists(CREDENTIALS_FILE):
        try:
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
            secure_log("INFO", f"Authenticated via {CREDENTIALS_FILE} file")
        except Exception as e:
            secure_log("ERROR", f"Failed to load {CREDENTIALS_FILE}: {type(e).__name__}")
    
    if not creds:
        raise FileNotFoundError(
            "Google credentials not found! Set GOOGLE_CREDENTIALS env var "
            f"or provide {CREDENTIALS_FILE} file."
        )
    
    _client = gspread.authorize(creds)
    secure_log("INFO", "Google Sheets authentication successful")
    return _client


def get_spreadsheet():
    """Get the main spreadsheet."""
    global _spreadsheet
    
    if _spreadsheet is not None:
        return _spreadsheet
    
    client = authenticate()
    _spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return _spreadsheet


def get_sheet(sheet_name: str):
    """Get a specific worksheet by name from the main spreadsheet."""
    spreadsheet = get_spreadsheet()
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        secure_log("ERROR", f"Worksheet '{sheet_name}' not found.")
        return None


def get_company_sheets() -> List[str]:
    """Get list of available company sheets.
    
    Returns:
        List of company sheet names
    """
    return COMPANY_SHEETS.copy()


def get_dompet_sheet(dompet_name: str):
    """Get a specific dompet sheet by name, auto-create with Split Layout if missing.
    
    Args:
        dompet_name: Name of the dompet sheet (e.g., 'CV HB (101)')
        
    Returns:
        gspread.Worksheet object
    """
    if dompet_name not in DOMPET_SHEETS:
        available_str = ', '.join(DOMPET_SHEETS)
        raise ValueError(
            f"Dompet '{dompet_name}' tidak valid.\n"
            f"Pilih dari: {available_str}"
        )
    
    spreadsheet = get_spreadsheet()
    
    try:
        sheet = spreadsheet.worksheet(dompet_name)
        secure_log("INFO", f"Using dompet sheet: {dompet_name}")
        return sheet
    except gspread.WorksheetNotFound:
        # Auto-create with Split Layout structure
        secure_log("INFO", f"Creating new dompet sheet: {dompet_name}")
        return _create_dompet_sheet_with_split_layout(spreadsheet, dompet_name)


def _create_dompet_sheet_with_split_layout(spreadsheet, dompet_name: str):
    """Create a new dompet sheet with Split Layout headers.
    
    Layout:
    - Row 7: PEMASUKAN (A), PENGELUARAN (J)
    - Row 8: Column headers for each block
    - Row 9+: Data
    """
    # Create sheet with enough columns (A-R = 18 columns)
    sheet = spreadsheet.add_worksheet(title=dompet_name, rows=100, cols=18)
    
    # Row 7: Section titles
    sheet.update_cell(SPLIT_LAYOUT_TITLE_ROW, 1, "PEMASUKAN")
    sheet.update_cell(SPLIT_LAYOUT_TITLE_ROW, 10, "PENGELUARAN")
    
    # Row 8: Column headers
    # Pemasukan headers (A-I)
    for i, header in enumerate(SPLIT_PEMASUKAN_HEADERS):
        sheet.update_cell(SPLIT_LAYOUT_HEADER_ROW, i + 1, header)
    
    # Pengeluaran headers (J-R)
    for i, header in enumerate(SPLIT_PENGELUARAN_HEADERS):
        sheet.update_cell(SPLIT_LAYOUT_HEADER_ROW, 10 + i, header)
    
    secure_log("INFO", f"Created Split Layout sheet: {dompet_name}")
    return sheet


def get_or_create_operational_sheet():
    """Get Operasional Ktr sheet, auto-create with headers if missing.
    
    Returns:
        gspread.Worksheet object
    """
    spreadsheet = get_spreadsheet()
    
    try:
        sheet = spreadsheet.worksheet(OPERASIONAL_SHEET_NAME)
        secure_log("INFO", f"Using operational sheet: {OPERASIONAL_SHEET_NAME}")
        return sheet
    except gspread.WorksheetNotFound:
        # Auto-create with headers
        secure_log("INFO", f"Creating new operational sheet: {OPERASIONAL_SHEET_NAME}")
        sheet = spreadsheet.add_worksheet(title=OPERASIONAL_SHEET_NAME, rows=100, cols=10)
        
        # Row 1: Headers
        for i, header in enumerate(OPERASIONAL_HEADERS):
            sheet.update_cell(OPERASIONAL_HEADER_ROW, i + 1, header)
        
        secure_log("INFO", f"Created operational sheet: {OPERASIONAL_SHEET_NAME}")
        return sheet


def _find_next_empty_row(sheet, check_column: int, start_row: int = 9) -> int:
    """Find the next empty row in a specific column.
    
    Args:
        sheet: gspread Worksheet
        check_column: 1-based column index to check
        start_row: Row to start checking from
        
    Returns:
        1-based row index of first empty cell
    """
    try:
        col_values = sheet.col_values(check_column)
        # Find first empty after start_row
        for i in range(start_row - 1, len(col_values)):
            if not col_values[i].strip():
                return i + 1  # Convert to 1-based
        return len(col_values) + 1  # Append after last
    except Exception:
        return start_row  # Fallback to start


def _count_entries_in_block(sheet, no_column: int, start_row: int = 9) -> int:
    """Count non-empty entries in a block (for auto-numbering)."""
    try:
        col_values = sheet.col_values(no_column)
        count = 0
        for i in range(start_row - 1, len(col_values)):
            if col_values[i].strip():
                count += 1
        return count
    except Exception:
        return 0


def append_project_transaction(
    transaction: Dict,
    sender_name: str,
    source: str,
    dompet_sheet: str,
    project_name: str
) -> Dict:
    """
    Append transaction to Split Layout dompet sheet.
    
    Logic:
    - Pemasukan: Write to Left block (columns A-I)
    - Pengeluaran: Write to Right block (columns J-R)
    
    Args:
        transaction: Dict with jumlah, keterangan, tipe, message_id
        sender_name: Name of person recording
        source: Source (WhatsApp/Telegram)
        dompet_sheet: Target dompet sheet name
        project_name: Project name to record
        
    Returns:
        Dict with success status and row info
    """
    try:
        sheet = get_dompet_sheet(dompet_sheet)
        tipe = transaction.get('tipe', 'Pengeluaran')
        
        # Determine which block to use
        if tipe == 'Pemasukan':
            cols = SPLIT_PEMASUKAN
            no_col = cols['NO']
        else:
            cols = SPLIT_PENGELUARAN
            no_col = cols['NO']
        
        # Find next empty row and count for numbering
        next_row = _find_next_empty_row(sheet, no_col, SPLIT_LAYOUT_DATA_START)
        entry_count = _count_entries_in_block(sheet, no_col, SPLIT_LAYOUT_DATA_START)
        
        # Build row data
        now = datetime.now()
        jumlah = abs(int(transaction.get('jumlah', 0)))
        keterangan = sanitize_input(str(transaction.get('keterangan', '')))[:200]
        safe_sender = sanitize_input(sender_name)[:50]
        safe_project = sanitize_input(project_name)[:100]
        message_id = transaction.get('message_id', '')
        
        row_data = [
            entry_count + 1,                    # No
            now.strftime('%H:%M:%S'),           # Waktu
            now.strftime('%Y-%m-%d'),           # Waktu/Tanggal
            jumlah,                             # Jumlah
            safe_project,                       # Project
            keterangan,                         # Keterangan
            safe_sender,                        # Oleh
            source,                             # Source
            message_id                          # MessageID
        ]
        
        # Write to correct column range
        start_col = cols['NO']
        
        # Batch update for efficiency
        cell_list = []
        for i, value in enumerate(row_data):
            cell_list.append(gspread.Cell(next_row, start_col + i, value))
        
        sheet.update_cells(cell_list, value_input_option='USER_ENTERED')
        
        secure_log("INFO", f"Project TX: {tipe} Rp{jumlah:,} -> {dompet_sheet} Row {next_row}")
        
        return {
            'success': True,
            'row': next_row,
            'dompet': dompet_sheet,
            'tipe': tipe,
            'jumlah': jumlah
        }
        
    except Exception as e:
        secure_log("ERROR", f"append_project_transaction failed: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def append_operational_transaction(
    transaction: Dict,
    sender_name: str,
    source: str,
    source_wallet: str,
    category: str = 'Lain Lain'
) -> Dict:
    """
    Append operational expense to Operasional Ktr sheet.
    Automatically appends "[Sumber: Wallet_Name]" to keterangan.
    
    Args:
        transaction: Dict with jumlah, keterangan, message_id
        sender_name: Name of person recording
        source: Source (WhatsApp/Telegram)
        source_wallet: Source wallet name (e.g., "CV HB (101)")
        category: Category (Gaji/ListrikAir/Konsumsi/Peralatan/Lain Lain)
        
    Returns:
        Dict with success status and row info
    """
    try:
        sheet = get_or_create_operational_sheet()
        
        # Find next row
        col_values = sheet.col_values(OPERASIONAL_COLS['NO'])
        next_row = len(col_values) + 1
        entry_count = len([v for v in col_values[OPERASIONAL_DATA_START - 1:] if v.strip()])
        
        # Build keterangan with source tag
        keterangan = sanitize_input(str(transaction.get('keterangan', '')))[:150]
        short_wallet = get_dompet_short_name(source_wallet)
        keterangan_with_source = f"{keterangan} [Sumber: {short_wallet}]"
        
        jumlah = abs(int(transaction.get('jumlah', 0)))
        safe_sender = sanitize_input(sender_name)[:50]
        message_id = transaction.get('message_id', '')
        
        row_data = [
            entry_count + 1,                        # No
            datetime.now().strftime('%Y-%m-%d'),    # Tanggal
            jumlah,                                 # JUMLAH
            keterangan_with_source,                 # KETERANGAN with [Sumber: X]
            safe_sender,                            # Oleh
            source,                                 # Source
            category,                               # Kategori
            message_id                              # MessageID
        ]
        
        sheet.append_row(row_data, value_input_option='USER_ENTERED')
        
        secure_log("INFO", f"Operational TX: Rp{jumlah:,} [{category}] from {short_wallet}")
        
        return {
            'success': True,
            'row': next_row,
            'source_wallet': source_wallet,
            'category': category,
            'jumlah': jumlah
        }
        
    except Exception as e:
        secure_log("ERROR", f"append_operational_transaction failed: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def get_company_sheet(company_name: str):
    """DEPRECATED: Use get_dompet_sheet instead.
    Kept for backward compatibility - maps company to dompet."""
    dompet = get_dompet_for_company(company_name)
    return get_dompet_sheet(dompet)


def get_available_projects() -> List[str]:
    """DEPRECATED: Use get_available_dompets instead."""
    return DOMPET_SHEETS.copy()


def get_project_sheet(company_name: str):
    """DEPRECATED: Alias for get_company_sheet for backward compatibility."""
    return get_company_sheet(company_name)


def get_all_categories() -> List[str]:
    """Get list of all allowed categories."""
    return ALLOWED_CATEGORIES.copy()


def _normalize_project_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _titlecase_preserve_acronyms(name: str) -> str:
    parts = name.split()
    output = []
    for part in parts:
        if part.isupper() and len(part) <= 3:
            output.append(part)
        else:
            output.append(part.capitalize())
    return " ".join(output)


def normalize_project_display_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        return ""
    if cleaned.isupper() or cleaned.islower():
        return _titlecase_preserve_acronyms(cleaned)
    return cleaned


def _prefer_display_name(current: str, candidate: str) -> str:
    if not current:
        return candidate
    if current == current.lower() and candidate != candidate.lower():
        return candidate
    return current


def append_transaction(transaction: Dict, sender_name: str, source: str = "Text", 
                       dompet_sheet: str = None, company: str = None, 
                       nama_projek: str = None,
                       company_sheet: str = None,
                       allow_queue: bool = True) -> int:
    """
    Append a single transaction to a dompet sheet.
    
    Args:
        transaction: Transaction dict with tanggal, kategori, keterangan, jumlah, tipe
        sender_name: Name of the person recording
        source: Input source (Text/Image/Voice)
        dompet_sheet: Target dompet sheet name (e.g., 'Dompet Holja')
        company: Company name (e.g., 'HOLLA', 'HOJJA', 'UMUM')
        nama_projek: Project name (REQUIRED) - use 'Saldo Umum' for wallet updates
        company_sheet: DEPRECATED - for backward compatibility, maps to dompet_sheet
        allow_queue: If True, queues transaction on network failure. Set False for retry worker.
    
    Transaction dict should have:
    - tanggal: YYYY-MM-DD
    - kategori: One of ALLOWED_CATEGORIES (Operasi Kantor, Bahan Alat, Gaji, Lain-lain)
    - keterangan: Description
    - jumlah: Amount (positive number)
    - tipe: "Pengeluaran" or "Pemasukan"
    
    Returns:
        True if successful, False otherwise
        
    Raises:
        ValueError: If dompet_sheet not specified or not found
    """
    try:
        # Handle backward compatibility: company_sheet -> dompet_sheet
        if company_sheet and not dompet_sheet:
            # Old code passed company_sheet, try to find corresponding dompet
            dompet_sheet = get_dompet_for_company(company_sheet)
            if not company:
                company = company_sheet
        
        # Dompet sheet is required
        if not dompet_sheet:
            raise ValueError(
                "Dompet harus dipilih.\n"
                f"Pilih dari: {', '.join(DOMPET_SHEETS)}"
            )
        
        # Validate dompet exists
        if dompet_sheet not in DOMPET_SHEETS:
            raise ValueError(
                f"Dompet '{dompet_sheet}' tidak valid.\n"
                f"Pilih dari: {', '.join(DOMPET_SHEETS)}"
            )
        
        sheet = get_dompet_sheet(dompet_sheet)
        
        # Validate and sanitize category
        kategori = validate_category(transaction.get('kategori', 'Lain-lain'))
        
        # Sanitize keterangan
        keterangan = sanitize_input(str(transaction.get('keterangan', '')))[:200]
        
        # Validate jumlah
        try:
            jumlah = abs(int(transaction.get('jumlah', 0)))
        except (ValueError, TypeError):
            jumlah = 0
        
        # Validate tipe
        tipe = transaction.get('tipe', 'Pengeluaran')
        if tipe not in ['Pemasukan', 'Pengeluaran']:
            tipe = 'Pengeluaran'
        
        # Sanitize sender name
        safe_sender = sanitize_input(sender_name)[:50]
        
        # Sanitize company
        # LOGIC: If company is actually a Dompet Name (e.g. "Dompet Evan") or "UMUM", store as "UMUM"
        original_company = str(company or 'UMUM')
        if original_company in DOMPET_SHEETS or original_company == "UMUM":
             safe_company = "UMUM"
        else:
             safe_company = sanitize_input(original_company)[:50]
        
        # REQUIRE nama_projek (no silent default)
        raw_nama_projek = str(nama_projek or "").strip()
        if not raw_nama_projek:
            raise ValueError(
                "Nama projek wajib diisi.\n"
                "Jika ini transaksi dompet (isi saldo/deposit), pakai nama_projek = 'Saldo Umum'."
            )
        safe_nama_projek = sanitize_input(raw_nama_projek)[:100]
        safe_nama_projek = normalize_project_display_name(safe_nama_projek)
        
        # Get message_id from transaction if provided
        message_id = transaction.get('message_id', '')
        
        # Calculate No (Auto-increment)
        try:
            existing_rows = len(sheet.col_values(2))
            next_no = existing_rows
            row_number = existing_rows + 1  # Row number where this will be inserted
        except Exception:
            next_no = 1
            row_number = 2  # After header

        # Row order: No, Tanggal, Company, Keterangan, Jumlah, Tipe, Oleh, Source, Kategori, Nama Projek, MessageID
        row = [
            next_no,  # A: Auto-generated Number
            transaction.get('tanggal', datetime.now().strftime('%Y-%m-%d')),  # B: Tanggal
            safe_company,  # C: Company
            keterangan,  # D: Keterangan (description)
            jumlah,  # E: Jumlah (amount)
            tipe,  # F: Tipe (Pengeluaran/Pemasukan)
            safe_sender,  # G: Oleh (recorded by)
            source,  # H: Source (Text/Image/Voice)
            kategori,  # I: Kategori
            safe_nama_projek,  # J: Nama Projek
            message_id,  # K: MessageID (for revision tracking)
        ]
        
        sheet.append_row(row, value_input_option='USER_ENTERED')
        invalidate_dashboard_cache()  # Force fresh data after write
        secure_log("INFO", f"Transaction added to {dompet_sheet}/{safe_company}: {kategori} - {jumlah} - {safe_nama_projek}")
        
        # Return row number for revision tracking
        return row_number
        
    except ValueError as e:
        secure_log("ERROR", f"Transaction error: {str(e)}")
        raise
    except Exception as e:
        # Layer 6: Offline Resilience
        # Check for network/transient errors
        is_transient = False
        
        # Check gspread API errors (usually 500, 502, 503, 429)
        if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
            if e.response.status_code in [429, 500, 502, 503, 504]:
                is_transient = True
                
        # Check connection errors
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            is_transient = True
            
        # Catch generic socket errors masked as other things
        if "socket" in str(e).lower() or "connection" in str(e).lower():
            is_transient = True
            
        if is_transient and allow_queue:
             secure_log("WARNING", f"Connection failed ({type(e).__name__}). Queueing transaction...")
             
             metadata = {
                 'sender_name': sender_name,
                 'source': source,
                 'dompet_sheet': dompet_sheet,
                 'company': company,
                 'nama_projek': nama_projek
             }
             
             try:
                 qid = add_to_retry_queue(transaction, metadata)
                 secure_log("INFO", f"Transaction queued offline with ID: {qid}")
                 return -1 # Special code for QUEUED
             except Exception as qe:
                 secure_log("ERROR", f"Failed to queue: {qe}")
                 # Fall through to raise original error if queuing also fails
        
        # Re-raise generic exceptions so they can be caught by the caller with details
        secure_log("ERROR", f"Failed to add transaction: {type(e).__name__} - {str(e)}")
        raise


def find_transaction_by_message_id(message_id: str) -> Optional[Dict]:
    """
    Find first transaction by its MessageID.
    Legacy wrapper for find_all_transactions_by_message_id.
    """
    results = find_all_transactions_by_message_id(message_id)
    return results[0] if results else None
        



def update_transaction_amount(dompet_sheet: str, row: int, new_amount: int) -> bool:
    """
    Update the Jumlah (amount) column for a specific transaction.
    
    Args:
        dompet_sheet: Name of the dompet sheet
        row: Row number (1-based)
        new_amount: New amount value
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Operational sheet
        if dompet_sheet == OPERASIONAL_SHEET_NAME:
            sheet = get_or_create_operational_sheet()
            sheet.update_cell(row, OPERASIONAL_COLS['JUMLAH'], new_amount)
            secure_log("INFO", f"Operational TX updated: {dompet_sheet} row {row} -> {new_amount}")
            return True
        
        sheet = get_dompet_sheet(dompet_sheet)
        
        # Split layout: detect which block has amount
        try:
            in_val = sheet.cell(row, SPLIT_PEMASUKAN['JUMLAH']).value
            out_val = sheet.cell(row, SPLIT_PENGELUARAN['JUMLAH']).value
        except Exception:
            in_val = None
            out_val = None
        
        if in_val:
            target_col = SPLIT_PEMASUKAN['JUMLAH']
        elif out_val:
            target_col = SPLIT_PENGELUARAN['JUMLAH']
        else:
            # Fallback to pengeluaran column
            target_col = SPLIT_PENGELUARAN['JUMLAH']
        
        sheet.update_cell(row, target_col, new_amount)
        
        secure_log("INFO", f"Transaction updated: {dompet_sheet} row {row} -> {new_amount}")
        return True
        
    except Exception as e:
        secure_log("ERROR", f"Update transaction error: {type(e).__name__}")
        return False

def append_transactions(transactions: List[Dict], sender_name: str, source: str = "Text",
                        dompet_sheet: str = None, company: str = None,
                        company_sheet: str = None) -> Dict:
    """Append multiple transactions to a dompet sheet.
    
    Args:
        transactions: List of transaction dicts (each may have 'nama_projek')
        sender_name: Name of the person recording
        source: Input source (Text/Image/Voice)
        dompet_sheet: Target dompet sheet name (e.g., 'Dompet Holja')
        company: Company name (e.g., 'HOLLA', 'UMUM')
        company_sheet: DEPRECATED - for backward compatibility
        
    Returns:
        Dict with success status, rows_added count, and errors
    """
    rows_added = 0
    queued_count = 0
    errors = []
    company_error = None
    
    # Backward compatibility
    if company_sheet and not dompet_sheet:
        dompet_sheet = get_dompet_for_company(company_sheet)
        if not company:
            company = company_sheet
    
    if not dompet_sheet:
        return {
            'success': False,
            'rows_added': 0,
            'queued_count': 0,
            'total_transactions': len(transactions),
            'errors': ['dompet_sheet_required'],
            'company_error': 'Dompet belum dipilih'
        }
    
    for t in transactions:
        try:
            nama_projek = t.get('nama_projek', '')
            # append_transaction now returns row number (truthy) or -1 (queued) or raises Exception
            res = append_transaction(t, sender_name, source, 
                                  dompet_sheet=dompet_sheet, 
                                  company=company,
                                  nama_projek=nama_projek)
            
            if res == -1:
                queued_count += 1
            elif res:
                rows_added += 1
                
        except ValueError as e:
            company_error = str(e)
            errors.append("dompet_not_found")
            break
        except Exception as e:
            # Capture generic errors (API issues, etc)
            company_error = f"{type(e).__name__}: {str(e)}"
            errors.append("transaction_failed")
            break    
            
    return {
        'success': (rows_added + queued_count) > 0,
        'rows_added': rows_added,
        'queued_count': queued_count,
        'total_transactions': len(transactions),
        'errors': errors,
        'company_error': company_error
    }

# --- Helper Functions untuk Safe Parsing ---

def _parse_date_safe(date_str):
    """Parse date safely with multiple formats."""
    if not date_str: return None
    for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except ValueError:
            continue
    return None

def _safe_get(lst, idx, default=''):
    """Safely get from list or return default."""
    try:
        if 0 <= idx < len(lst):
            return lst[idx]
    except:
        pass
    return default

def _parse_amount(amt_str):
    """Parse amount safely."""
    try:
        return int(float(str(amt_str).replace(',', '').replace('Rp', '').replace('.', '').strip() or 0))
    except:
        return 0

def get_all_data(days: int = 30) -> List[Dict]:
    """
    Get all transaction data from ALL dompet sheets.
    Handles SPLIT LAYOUT (Pemasukan Left, Pengeluaran Right) for correct context.
    
    Args:
        days: Optional, only get data from last N days
        
    Returns:
        List of transaction dicts with company and nama_projek
    """
    try:
        from config.constants import (
            SPLIT_PEMASUKAN, SPLIT_PENGELUARAN, SPLIT_LAYOUT_DATA_START,
            OPERASIONAL_SHEET_NAME, OPERASIONAL_COLS, OPERASIONAL_DATA_START
        )
        # DOMPET_COMPANIES should come from config.wallets, not config.constants
        from config.wallets import DOMPET_COMPANIES
        
        spreadsheet = get_spreadsheet()
        data = []
        
        cutoff_date = None
        if days:
            cutoff_date = datetime.now() - timedelta(days=days)
        
        # 1. PROCESS OPERASIONAL SHEET (Standard Layout)
        try:
            op_sheet = spreadsheet.worksheet(OPERASIONAL_SHEET_NAME)
            op_rows = op_sheet.get_all_values()
            
            # Operasional uses standard layout starting at row 2
            # Indices (0-based): TANGGAL=1, JUMLAH=2, KET=3, OLEH=4, SOURCE=5, KAT=6
            for row in op_rows[OPERASIONAL_DATA_START-1:]:
                if len(row) < 3: continue
                try:
                    date_str = row[OPERASIONAL_COLS['TANGGAL']-1]
                    amt_str = row[OPERASIONAL_COLS['JUMLAH']-1]
                    
                    if not date_str or not amt_str: continue
                    
                    # Parse Date
                    row_date = None
                    for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
                        try:
                            row_date = datetime.strptime(date_str, fmt)
                            break
                        except ValueError: continue
                    
                    if not row_date: continue
                    if cutoff_date and row_date < cutoff_date: continue
                    
                    # Parse Amount
                    amount = int(float(str(amt_str).replace(',', '').replace('Rp', '').replace('.', '').strip() or 0))
                    
                    data.append({
                        'tanggal': date_str,
                        'keterangan': row[OPERASIONAL_COLS['KETERANGAN']-1] if len(row) >= OPERASIONAL_COLS['KETERANGAN'] else '',
                        'jumlah': amount,
                        'tipe': 'Pengeluaran', # Operasional is always expense
                        'oleh': row[OPERASIONAL_COLS['OLEH']-1] if len(row) >= OPERASIONAL_COLS['OLEH'] else '',
                        'kategori': row[OPERASIONAL_COLS['KATEGORI']-1] if len(row) >= OPERASIONAL_COLS['KATEGORI'] else 'Lain-lain',
                        'company_sheet': 'Operasional Kantor',
                        'nama_projek': 'Operasional'
                    })
                except:
                    continue
        except Exception as e:
            secure_log("WARNING", f"Error reading Operasional: {e}")

        # 2. PROCESS WALLET SHEETS (Split Layout)
        for dompet in DOMPET_SHEETS:
            try:
                sheet = spreadsheet.worksheet(dompet)
                all_values = sheet.get_all_values()
                
                # Get Company Name mapping
                # Use the canonical Dompet Name (key) as the Company Name
                # DOMPET_COMPANIES values are lists, so we must use 'k' (string) not 'v' (list)
                company_name = next((k for k,v in DOMPET_COMPANIES.items() if k.lower() in dompet.lower()), dompet)
                
                # Skip up to data start
                for row in all_values[SPLIT_LAYOUT_DATA_START-1:]:
                    if not row: continue
                    
                    # --- A. CHECK PEMASUKAN LEFT BLOCK ---
                    # Columns A-I (Indices 0-8)
                    try:
                        idx_tgl = SPLIT_PEMASUKAN['TANGGAL'] - 1 # Index 2
                        idx_jml = SPLIT_PEMASUKAN['JUMLAH'] - 1  # Index 3
                        
                        if len(row) > idx_jml and row[idx_tgl] and row[idx_jml]:
                            date_str = row[idx_tgl]
                            amt_str = row[idx_jml]
                            
                            # Parse Date
                            row_date = None
                            for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
                                try:
                                    row_date = datetime.strptime(date_str, fmt)
                                    break
                                except: continue
                                
                            if row_date and (not cutoff_date or row_date >= cutoff_date):
                                amount = int(float(str(amt_str).replace(',', '').replace('Rp', '').replace('.', '').strip() or 0))
                                
                                data.append({
                                    'tanggal': date_str,
                                    'keterangan': row[SPLIT_PEMASUKAN['KETERANGAN']-1] if len(row) >= SPLIT_PEMASUKAN['KETERANGAN'] else '',
                                    'jumlah': amount,
                                    'tipe': 'Pemasukan',
                                    'nama_projek': row[SPLIT_PEMASUKAN['PROJECT']-1] if len(row) >= SPLIT_PEMASUKAN['PROJECT'] else '',
                                    'company_sheet': company_name,
                                    'kategori': 'Income'
                                })
                    except: pass
                    
                    # --- B. CHECK PENGELUARAN RIGHT BLOCK ---
                    # Columns J-R (Indices 9-17)
                    try:
                        idx_tgl = SPLIT_PENGELUARAN['TANGGAL'] - 1 # Index 11
                        idx_jml = SPLIT_PENGELUARAN['JUMLAH'] - 1  # Index 12
                        
                        if len(row) > idx_jml and row[idx_tgl] and row[idx_jml]:
                            date_str = row[idx_tgl]
                            amt_str = row[idx_jml]
                            
                            # Parse Date
                            row_date = None
                            for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
                                try:
                                    row_date = datetime.strptime(date_str, fmt)
                                    break
                                except: continue
                                
                            if row_date and (not cutoff_date or row_date >= cutoff_date):
                                amount = int(float(str(amt_str).replace(',', '').replace('Rp', '').replace('.', '').strip() or 0))
                                
                                data.append({
                                    'tanggal': date_str,
                                    'keterangan': row[SPLIT_PENGELUARAN['KETERANGAN']-1] if len(row) >= SPLIT_PENGELUARAN['KETERANGAN'] else '',
                                    'jumlah': amount,
                                    'tipe': 'Pengeluaran',
                                    'nama_projek': row[SPLIT_PENGELUARAN['PROJECT']-1] if len(row) >= SPLIT_PENGELUARAN['PROJECT'] else '',
                                    'company_sheet': company_name,
                                    'kategori': 'Project Expense'
                                })
                    except: pass
                        
            except Exception as e:
                secure_log("WARNING", f"Could not read dompet {dompet}: {type(e).__name__}")
                continue
        
        return data
        
    except Exception as e:
        secure_log("ERROR", f"Failed to get data: {type(e).__name__}")
        return []



def check_duplicate_transaction(new_amount: int, new_desc: str, new_project: str, 
                              company: str, days_lookback: int = 2) -> tuple:
    """
    Check for potential duplicate transactions (Layer 5: Semantic Duplicate Detection).
    
    Args:
        new_amount: Amount of new transaction
        new_desc: Description of new transaction
        new_project: Project name
        company: Company/Company Sheet name
        days_lookback: How many days back to check
        
    Returns:
        (is_duplicate: bool, warning_message: str or None)
    """
    try:
        from difflib import SequenceMatcher
        
        # Pull recent data
        recent_data = get_all_data(days=days_lookback)
        
        normalized_new_desc = new_desc.lower().strip()
        normalized_new_proj = (new_project or "").lower().strip()
        
        potential_dupes = []
        
        for txn in recent_data:
            # Check 1: Company match (if known)
            txn_company = (txn.get('company_sheet') or "").strip()
            if company and company != "Unknown" and txn_company != "Unknown":
                if company.lower() != txn_company.lower():
                    continue

            # Check 2: Amount exact match
            # (Relaxed check: allow slight variance not implemented yet to be safe, stick to exact amount for now)
            if txn['jumlah'] != new_amount:
                continue
                
            # Check 3: Description Semantic Similarity
            # Calculate similarity ratio (0.0 to 1.0)
            txn_desc = txn['keterangan'].lower().strip()
            similarity = SequenceMatcher(None, normalized_new_desc, txn_desc).ratio()
            
            # Check 4: Project Match (if both exist)
            txn_proj = (txn.get('nama_projek') or "").lower().strip()
            project_mismatch = False
            if normalized_new_proj and txn_proj:
                 if normalized_new_proj != txn_proj:
                     project_mismatch = True
            
            # Decision Logic
            # High similarity (> 0.75) AND Same Amount AND Not different projects
            if similarity > 0.75 and not project_mismatch:
                potential_dupes.append(txn)
                
        if potential_dupes:
            # Construct warning message
            dupe = potential_dupes[0]
            msg = (f"⚠️ Transaksi ini mirip dengan yang sudah ada:\n"
                   f"📅 {dupe['tanggal']} | {dupe['keterangan']} | Rp {dupe['jumlah']:,}\n"
                   f"📍 {dupe.get('company_sheet', 'Unknown')} ({dupe.get('nama_projek', '-')})\n\n"
                   f"Yakin mau simpan lagi? (Reply Y untuk lanjut simpan)")
            return True, msg
            
        return False, None
        
    except Exception as e:
        secure_log("WARNING", f"Duplicate check failed: {str(e)}")
        return False, None


def get_summary(days: int = 30) -> Dict:
    """Get summary statistics for all transactions."""
    data = get_all_data(days)
    
    total_pengeluaran = sum(d['jumlah'] for d in data if d.get('tipe') == 'Pengeluaran')
    total_pemasukan = sum(d['jumlah'] for d in data if d.get('tipe') == 'Pemasukan')
    
    # Group by kategori
    by_kategori = {}
    for d in data:
        if d.get('tipe') == 'Pengeluaran':
            kat = d.get('kategori', 'Lainnya')
            by_kategori[kat] = by_kategori.get(kat, 0) + d['jumlah']
    
    # Group by oleh (who recorded)
    by_oleh = {}
    for d in data:
        if d.get('tipe') == 'Pengeluaran':
            oleh = d.get('oleh', 'Unknown')
            by_oleh[oleh] = by_oleh.get(oleh, 0) + d['jumlah']
            
    # Group by project (Nama Projek) - NOW includes income AND expense for P/L
    by_projek = {}
    for d in data:
        proj = d.get('nama_projek', '').strip()
        if proj:
            proj_key = _normalize_project_key(proj)
            display_name = normalize_project_display_name(proj)
            if proj_key not in by_projek:
                by_projek[proj_key] = {
                    'name': display_name,
                    'income': 0,
                    'expense': 0,
                    'profit_loss': 0
                }
            else:
                by_projek[proj_key]['name'] = _prefer_display_name(
                    by_projek[proj_key]['name'],
                    display_name
                )
            if d.get('tipe') == 'Pemasukan':
                by_projek[proj_key]['income'] += d['jumlah']
            elif d.get('tipe') == 'Pengeluaran':
                by_projek[proj_key]['expense'] += d['jumlah']
    
    # Calculate profit/loss for each project
    for proj_key in by_projek:
        by_projek[proj_key]['profit_loss'] = (
            by_projek[proj_key]['income'] - by_projek[proj_key]['expense']
        )
    
    return {
        'period_days': days,
        'total_pengeluaran': total_pengeluaran,
        'total_pemasukan': total_pemasukan,
        'saldo': total_pemasukan - total_pengeluaran,
        'transaction_count': len(data),
        'by_kategori': by_kategori,
        'by_oleh': by_oleh,
        'by_projek': by_projek
    }


def check_budget_alert(new_amount: int = 0) -> Dict:
    """Check if approaching or exceeding budget - uses dashboard summary for multi-project."""
    # Use dashboard summary for multi-project data aggregation
    try:
        dashboard_data = get_dashboard_summary()
        spent = dashboard_data.get('total_expense', 0)
    except Exception:
        # Fallback: try legacy single-sheet approach
        try:
            data = get_all_data()
            spent = sum(d['jumlah'] for d in data if d.get('tipe') == 'Pengeluaran')
        except Exception:
            spent = 0
    
    spent += new_amount
    
    budget = DEFAULT_BUDGET
    remaining = budget - spent
    percent_used = (spent / budget * 100) if budget > 0 else 0
    
    alert = {
        'budget': budget,
        'spent': spent,
        'remaining': remaining,
        'percent_used': round(percent_used, 1),
        'alert_type': None,
        'message': None
    }
    
    if percent_used >= 100:
        alert['alert_type'] = 'OVER_BUDGET'
        alert['message'] = "🚨 *OVER BUDGET!* Pengeluaran melebihi budget!"
    elif percent_used >= BUDGET_WARNING_PERCENT:
        alert['alert_type'] = 'WARNING'
        alert['message'] = f"⚠️ *Budget Warning!* Sudah terpakai {percent_used:.0f}%"
    
    return alert


def format_data_for_ai(days: int = 30) -> str:
    """
    Format all data as text for AI context.
    Used for /tanya queries.
    SECURED: No sensitive data included.
    Includes transaction details with nama_projek for specific queries.
    """
    # Get raw transaction data
    data = get_all_data(days)
    
    if not data:
        return "Tidak ada data transaksi."
    
    # Calculate summary
    total_pengeluaran = sum(d['jumlah'] for d in data if d.get('tipe') == 'Pengeluaran')
    total_pemasukan = sum(d['jumlah'] for d in data if d.get('tipe') == 'Pemasukan')
    
    lines = [
        f"DATA KEUANGAN ({days} HARI TERAKHIR)",
        "=" * 40,
        "",
        f"Total Pengeluaran: Rp {total_pengeluaran:,}".replace(',', '.'),
        f"Total Pemasukan: Rp {total_pemasukan:,}".replace(',', '.'),
        f"Saldo: Rp {total_pemasukan - total_pengeluaran:,}".replace(',', '.'),
        f"Jumlah Transaksi: {len(data)}",
        "",
    ]
    
    # Group by kategori
    by_kategori = {}
    for d in data:
        if d.get('tipe') == 'Pengeluaran':
            kat = d.get('kategori', 'Lain-lain')
            by_kategori[kat] = by_kategori.get(kat, 0) + d['jumlah']
    
    if by_kategori:
        lines.append("<PER_KATEGORI>")
        for kat, amount in sorted(by_kategori.items(), key=lambda x: -x[1]):
            lines.append(f"  - {kat}: Rp {amount:,}".replace(',', '.'))
        lines.append("</PER_KATEGORI>")
        lines.append("")
    
    # Group by nama_projek - include BOTH income and expense (case-insensitive)
    by_projek = {}
    for d in data:
        projek = d.get('nama_projek', '').strip()
        if projek:
            projek_key = _normalize_project_key(projek)
            display_name = normalize_project_display_name(projek)
            if projek_key not in by_projek:
                by_projek[projek_key] = {
                    'name': display_name,
                    'income': 0,
                    'expense': 0,
                    'company': d.get('company_sheet', '')
                }
            else:
                by_projek[projek_key]['name'] = _prefer_display_name(
                    by_projek[projek_key]['name'],
                    display_name
                )
            if d.get('tipe') == 'Pengeluaran':
                by_projek[projek_key]['expense'] += d['jumlah']
            elif d.get('tipe') == 'Pemasukan':
                by_projek[projek_key]['income'] += d['jumlah']
    
    if by_projek:
        lines.append("<PER_NAMA_PROJEK>")
        for _, info in sorted(by_projek.items(), key=lambda x: -(x[1]['expense'] + x[1]['income'])):
            profit_loss = info['income'] - info['expense']
            status = "UNTUNG" if profit_loss > 0 else "RUGI" if profit_loss < 0 else "NETRAL"
            lines.append(f"  - {info['name']} ({info['company']}): Pemasukan={info['income']:,} | Pengeluaran={info['expense']:,} | P/L={profit_loss:,} ({status})".replace(',', '.'))
        lines.append("</PER_NAMA_PROJEK>")
        lines.append("")
    
    # Group by company
    by_company = {}
    for d in data:
         comp = d.get('company_sheet', 'Unknown')
         if comp not in by_company:
             by_company[comp] = 0
         by_company[comp] += d['jumlah']
         
    if by_company:
        lines.append("<PER_COMPANY_SHEET>")
        for comp, amt in by_company.items():
             lines.append(f"  - {comp}: Total Volume Rp {amt:,}".replace(',', '.'))
        lines.append("</PER_COMPANY_SHEET>")
        lines.append("")
        
    # Recent transactions details - IMPROVED CONTEXT
    lines.append("<DETAIL_TRANSAKSI_TERBARU>")
    # Show last 30 transactions
    recent = sorted(data, key=lambda x: x.get('tanggal', ''), reverse=True)[:30]
    for i, d in enumerate(recent):
        amt = f"Rp {d['jumlah']:,}".replace(',', '.')
        proj = f" ({d['nama_projek']})" if d.get('nama_projek') else ""
        lines.append(f"{i+1}. {d['tanggal']} - {d['kategori']} - {d['keterangan']} - {amt} ({d['tipe']}){proj} [{d['company_sheet']}]")
    lines.append("</DETAIL_TRANSAKSI_TERBARU>")
    
    return '\n'.join(lines)


def format_dashboard_message() -> str:
    """
    Format dashboard data as a chat message.
    Used for enhanced /status command.
    Shows breakdowns by Wallet (Dompet) and Company.
    """
    data = get_dashboard_summary()
    
    # Overall profit/loss indicator
    if data['balance'] > 0:
        status = "🟢 PROFIT"
    elif data['balance'] < 0:
        status = "🔴 RUGI"
    else:
        status = "⚪ NETRAL"
    
    lines = [
        f"📊 *DASHBOARD KEUANGAN* {status}",
        "",
        f"💼 Total Company: {data['company_count']}",
        f"📝 Total Transaksi: {data['total_transactions']}",
        "",
        f"💰 Total Pemasukan: Rp {data['total_income']:,}".replace(',', '.'),
        f"💸 Total Pengeluaran: Rp {data['total_expense']:,}".replace(',', '.'),
        f"📈 *Profit/Loss Global: Rp {data['balance']:,}*".replace(',', '.'),
        ""
    ]
    
    # 1. SALDO DOMPET (Physical Wallets)
    if data['dompet_summary']:
        lines.append("*💰 SALDO DOMPET*")
        for dompet, info in data['dompet_summary'].items():
            bal = info['bal']
            icon = "🟢" if bal >= 0 else "🔴"
            lines.append(f"{icon} {dompet}: Rp {bal:,}".replace(',', '.'))
        lines.append("")
        
    # 2. PERFORMA COMPANY (Profit/Loss per Company)
    if data['company_summary']:
        lines.append("*🏢 PERFORMA COMPANY*")
        sorted_companies = sorted(data['company_summary'].items(), key=lambda x: x[0])
        for comp, info in sorted_companies:
            pl = info['bal']
            status_icon = "📈" if pl > 0 else "📉" if pl < 0 else "➖"
            lines.append(f"{status_icon} *{comp}*: Rp {pl:,}".replace(',', '.'))
            # Optional: Show detail line? Maybe too long
            # lines.append(f"   (Inc: {info['inc']:,} | Exp: {info['exp']:,})".replace(',', '.'))
    
    lines.append("\n_Ketik /laporan untuk detail per projek_")
    
    return '\n'.join(lines)


def generate_report(days: int = 7) -> Dict:
    """Generate spending report."""
    summary = get_summary(days)
    
    return {
        'period': f'Last {days} days',
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'summary': summary,
        'grand_total': summary['total_pengeluaran']
    }


def format_report_message(report: Dict) -> str:
    """Format report as chat message."""
    s = report['summary']
    
    percent = (s['total_pengeluaran'] / DEFAULT_BUDGET * 100) if DEFAULT_BUDGET > 0 else 0
    status = "🔴" if percent >= 100 else "🟡" if percent >= 80 else "🟢"
    
    lines = [
        f"📊 *LAPORAN KEUANGAN* {status}",
        f"📅 Periode: {report['period']}",
        f"🕐 Generated: {report['generated_at']}",
        "",
        f"💸 Pengeluaran: Rp {s['total_pengeluaran']:,}".replace(',', '.'),
        f"💰 Pemasukan: Rp {s['total_pemasukan']:,}".replace(',', '.'),
        f"📊 Saldo: Rp {s['saldo']:,}".replace(',', '.'),
        f"📝 Transaksi: {s['transaction_count']}",
        "",
    ]
    
    if s['by_kategori']:
        lines.append("*Per Kategori:*")
        for kat, amount in sorted(s['by_kategori'].items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  • {kat}: Rp {amount:,}".replace(',', '.'))
            
    if s.get('by_projek'):
        lines.append("")
        lines.append("*Top 5 Projek (Laba/Rugi):*")
        # Sort by absolute profit/loss value (most significant first)
        sorted_projek = sorted(
            s['by_projek'].items(), 
            key=lambda x: abs(x[1]['profit_loss']), 
            reverse=True
        )[:5]
        for _, info in sorted_projek:
            pl = info['profit_loss']
            icon = "📈" if pl > 0 else "📉" if pl < 0 else "➖"
            status_text = "UNTUNG" if pl > 0 else "RUGI" if pl < 0 else "NETRAL"
            lines.append(f"  {icon} {info['name']}: Rp {pl:,} ({status_text})".replace(',', '.'))
    
    return '\n'.join(lines)


def get_wallet_balances() -> Dict:
    """
    Calculate REAL wallet balances using Virtual Balance formula:
    
    Real Balance = (Pemasukan in Dompet Sheet - Pengeluaran in Dompet Sheet)
                   - (Operational expenses where Sumber = this Dompet)
    
    This reads directly from Split Layout sheets (CV HB, TX SBY, TX BALI)
    and the Operasional Ktr sheet for operational debits.
    """
    balances = {}
    
    # 1. Calculate base balance from each dompet sheet (Split Layout)
    for dompet in DOMPET_SHEETS:
        try:
            sheet = get_dompet_sheet(dompet)
            
            # Sum Pemasukan (Left block, Column D = JUMLAH)
            pemasukan_col = sheet.col_values(SPLIT_PEMASUKAN['JUMLAH'])
            total_masuk = 0
            for v in pemasukan_col[SPLIT_LAYOUT_DATA_START - 1:]:  # Skip headers
                total_masuk += _parse_amount(v)
            
            # Sum Pengeluaran (Right block, Column M = JUMLAH)
            pengeluaran_col = sheet.col_values(SPLIT_PENGELUARAN['JUMLAH'])
            total_keluar = 0
            for v in pengeluaran_col[SPLIT_LAYOUT_DATA_START - 1:]:
                total_keluar += _parse_amount(v)
            
            balances[dompet] = {
                'pemasukan': total_masuk,
                'pengeluaran': total_keluar,
                'internal_balance': total_masuk - total_keluar,
                'operational_debit': 0  # Will be calculated next
            }
            
        except Exception as e:
            secure_log("ERROR", f"Error reading dompet {dompet}: {e}")
            balances[dompet] = {
                'pemasukan': 0,
                'pengeluaran': 0,
                'internal_balance': 0,
                'operational_debit': 0
            }
    
    # 2. Parse Operasional Ktr sheet and debit from source wallets
    try:
        op_sheet = get_or_create_operational_sheet()
        all_rows = op_sheet.get_all_values()[OPERASIONAL_DATA_START - 1:]  # Skip header
        
        for row in all_rows:
            if len(row) >= OPERASIONAL_COLS['KETERANGAN']:
                keterangan = row[OPERASIONAL_COLS['KETERANGAN'] - 1]
                jumlah_str = row[OPERASIONAL_COLS['JUMLAH'] - 1] if len(row) >= OPERASIONAL_COLS['JUMLAH'] else '0'
                amount = _parse_amount(jumlah_str)
                
                # Extract source wallet from "[Sumber: XXX]"
                match = re.search(r'\[Sumber:\s*([^\]]+)\]', keterangan)
                if match:
                    source_wallet_short = match.group(1).strip()
                    # Match to canonical dompet name
                    for dompet in DOMPET_SHEETS:
                        short_name = get_dompet_short_name(dompet)
                        if source_wallet_short.lower() == short_name.lower():
                            balances[dompet]['operational_debit'] += amount
                            break
    except Exception as e:
        secure_log("ERROR", f"Error parsing operational sheet: {e}")
    
    # 3. Calculate Final REAL Balance
    for dompet in balances:
        balances[dompet]['saldo'] = balances[dompet]['internal_balance'] - balances[dompet]['operational_debit']
        
    return balances


def format_dashboard_message(summary: Dict) -> str:
    """Format dashboard summary as chat message."""
    lines = ["� *DASHBOARD KEUANGAN*", "=" * 25, ""]
    
    # Global Summary
    lines.append(f"💰 Income: Rp {summary['total_income']:,}".replace(',', '.'))
    lines.append(f"💸 Expense: Rp {summary['total_expense']:,}".replace(',', '.'))
    lines.append(f"📈 Balance: Rp {summary['balance']:,}".replace(',', '.'))
    lines.append(f"📝 Total Tx: {summary['total_transactions']}")
    lines.append("")
    
    # Validasi Dompet (Real vs Virtual) -> Update: Just say Real
    lines.append("*Status Saldo Dompet (Real)*:")
    for dompet, stats in summary['dompet_summary'].items():
        short = get_dompet_short_name(dompet)
        bal = stats['bal']
        icon = "🟢" if bal >= 0 else "🔴"
        lines.append(f"{icon} {short}: Rp {bal:,}".replace(',', '.'))
        
    lines.append("")
    lines.append("*Status Projects (Est)*:")
    for company, stats in summary['company_summary'].items():
        bal = stats['bal']
        icon = "📈" if bal >= 0 else "📉"
        lines.append(f"{icon} {company}: Rp {bal:,}".replace(',', '.'))
        
    lines.append("")
    lines.append(f"_Last Update: {datetime.now().strftime('%H:%M')}_")
    
    return "\n".join(lines)


def _parse_amount(value) -> int:
    """Parse amount string to integer, handling various formats."""
    if not value:
        return 0
    try:
        # Remove common formatting
        clean = str(value).replace('.', '').replace(',', '').replace('Rp', '').replace(' ', '').strip()
        return int(float(clean))
    except (ValueError, TypeError):
        return 0

def test_connection() -> bool:
    """Test connection to Google Sheets."""
    try:
        spreadsheet = get_spreadsheet()
        sheets = spreadsheet.worksheets()
        secure_log("INFO", f"Connected! Found {len(sheets)} sheets")
        return True
    except Exception as e:
        secure_log("ERROR", f"Connection failed: {type(e).__name__}")
        return False


# ===================== STATUS/SUMMARY FUNCTIONS =====================
# Note: Dashboard sheet is now managed by Google Apps Script (Dashboard.gs)
# These functions provide data for /status command in Telegram

# Dashboard Cache
_dashboard_cache = None
_dashboard_last_update = 0
DASHBOARD_CACHE_TTL = 60  # 60 seconds

def invalidate_dashboard_cache():
    """Invalidate dashboard cache (call this after adding transactions)."""
    global _dashboard_cache
    _dashboard_cache = None
    secure_log("INFO", "Dashboard cache invalidated")


def get_dashboard_summary():
    """Get dashboard summary with caching."""
    global _dashboard_cache, _dashboard_last_update

    try:
        current_time = datetime.now()
        
        # Cache TTL check (e.g. 5 minutes)
        if _dashboard_cache and _dashboard_last_update:
            if (current_time - _dashboard_last_update).total_seconds() < DASHBOARD_CACHE_TTL:
                return _dashboard_cache
        
        total_income = 0
        total_expense = 0
        total_transactions = 0
        
        dompet_summary = {}
        company_summary = {}

        # Iterate 3 Split-Layout Wallets
        for dompet in DOMPET_SHEETS:
            dompet_summary[dompet] = {'inc': 0, 'exp': 0, 'bal': 0}
            
            try:
                sheet = get_dompet_sheet(dompet)
                
                # --- READ PEMASUKAN BLOCK (Left) ---
                # Col D (4) = Amount, Col C (3) = Date, Col E (5) = Project
                inc_vals = sheet.col_values(SPLIT_PEMASUKAN['JUMLAH'])
                
                # We assume if there is an amount, it's a valid transaction
                for val in inc_vals[SPLIT_LAYOUT_DATA_START-1:]:
                    amt = _parse_amount(val)
                    if amt > 0:
                        total_income += amt
                        dompet_summary[dompet]['inc'] += amt
                        total_transactions += 1
                        
                        # In new layout, map to Wallet Name
                        c_name = get_dompet_short_name(dompet) 
                        if c_name not in company_summary:
                            company_summary[c_name] = {'inc': 0, 'exp': 0, 'bal': 0}
                        company_summary[c_name]['inc'] += amt

                # --- READ PENGELUARAN BLOCK (Right) ---
                # Col M (13) = Amount, Col N (14) = Project
                exp_vals = sheet.col_values(SPLIT_PENGELUARAN['JUMLAH'])
                
                for val in exp_vals[SPLIT_LAYOUT_DATA_START-1:]:
                    amt = _parse_amount(val)
                    if amt > 0:
                        total_expense += amt
                        dompet_summary[dompet]['exp'] += amt
                        total_transactions += 1
                        
                        c_name = get_dompet_short_name(dompet)
                        if c_name not in company_summary:
                            company_summary[c_name] = {'inc': 0, 'exp': 0, 'bal': 0}
                        company_summary[c_name]['exp'] += amt

                # Calc Balance
                dompet_summary[dompet]['bal'] = dompet_summary[dompet]['inc'] - dompet_summary[dompet]['exp']
                
            except Exception as e:
                secure_log("ERROR", f"Dashboard error {dompet}: {e}")
                continue

        # --- PROCESS OPERATIONAL DEBITS FOR DASHBOARD ---
        try:
            from config.wallets import get_dompet_short_name
            import re
            
            # Re-use logic from get_wallet_balances to find operational debits
            op_sheet = get_or_create_operational_sheet()
            # Get values - checking existence first
            op_data = op_sheet.get_all_values()
            
            if len(op_data) >= OPERASIONAL_DATA_START:
                for row in op_data[OPERASIONAL_DATA_START-1:]:
                    if not row or len(row) < OPERASIONAL_COLS['JUMLAH']: continue
                    
                    try:
                        # Parse amount
                        amt_str = row[OPERASIONAL_COLS['JUMLAH']-1]
                        amount = _parse_amount(amt_str)
                        if amount <= 0: continue
                        
                        # Add to global expense
                        total_expense += amount
                        
                        # Check source
                        keterangan = row[OPERASIONAL_COLS['KETERANGAN']-1] if len(row) >= OPERASIONAL_COLS['KETERANGAN'] else ""
                        match = re.search(r'\[Sumber:\s*([^\]]+)\]', keterangan)
                        if match:
                            source_short = match.group(1).strip()
                            # Find matching dompet in summary
                            for dompet in DOMPET_SHEETS:
                                d_short = get_dompet_short_name(dompet)
                                if source_short.lower() == d_short.lower():
                                    # DEBIT the wallet balance directly
                                    dompet_summary[dompet]['exp'] += amount # Add to expense tracking for that wallet
                                    # Note: Balances are calculated in next step
                                    break
                    except:
                        continue
        except Exception as e:
            secure_log("WARNING", f"Dashboard operational calc failed: {e}")

        except Exception as e:
            secure_log("WARNING", f"Dashboard operational calc failed: {e}")

        # Calc Company Balances
        for c in company_summary:
            company_summary[c]['bal'] = company_summary[c]['inc'] - company_summary[c]['exp']
            
        # RE-CALCULATE Dompet Balances (Critical: Update balance after Operational Debits)
        for d in dompet_summary:
            dompet_summary[d]['bal'] = dompet_summary[d]['inc'] - dompet_summary[d]['exp']

        # Update Cache
        _dashboard_cache = {
            'total_income': total_income,
            'total_expense': total_expense,
            'balance': total_income - total_expense,
            'total_transactions': total_transactions,
            'company_count': len(company_summary),
            'dompet_summary': dompet_summary,
            'company_summary': company_summary
        }
        _dashboard_last_update = current_time
        
        secure_log("INFO", "Dashboard cache updated")
        return _dashboard_cache
        
    except Exception as e:
        secure_log("ERROR", f"Dashboard summary failed: {type(e).__name__}")
        return {
            'total_income': 0, 'total_expense': 0, 'balance': 0,
            'total_transactions': 0, 'company_count': 0,
            'dompet_summary': {},
            'company_summary': {}
        }






def find_all_transactions_by_message_id(message_id: str) -> List[Dict]:
    """
    Find ALL transactions by MessageID across all dompet sheets.
    Useful for revisions of multi-item messages.
    """
    if not message_id:
        return []
    
    results = []

    def _match_message_id(cell_value: str, target: str) -> bool:
        if not cell_value or not target:
            return False
        if cell_value == target:
            return True
        # Support combined format: event_id|idx
        if '|' in cell_value:
            parts = [p.strip() for p in cell_value.split('|') if p.strip()]
            if target in parts:
                return True
            if cell_value.startswith(f"{target}|"):
                return True
        return False
    
    try:
        # Search dompet sheets (split layout)
        for dompet in DOMPET_SHEETS:
            try:
                sheet = get_dompet_sheet(dompet)
                if not sheet:
                    continue

                in_ids = sheet.col_values(SPLIT_PEMASUKAN['MESSAGE_ID'])
                out_ids = sheet.col_values(SPLIT_PENGELUARAN['MESSAGE_ID'])
                max_len = max(len(in_ids), len(out_ids))
                
                for row_idx in range(SPLIT_LAYOUT_DATA_START - 1, max_len):
                    row_number = row_idx + 1
                    mid_in = in_ids[row_idx] if row_idx < len(in_ids) else ""
                    mid_out = out_ids[row_idx] if row_idx < len(out_ids) else ""
                    
                    if _match_message_id(mid_in, message_id):
                        row_data = sheet.row_values(row_number)
                        results.append({
                            'dompet': dompet,
                            'row': row_number,
                            'amount': int(row_data[SPLIT_PEMASUKAN['JUMLAH'] - 1]) if len(row_data) >= SPLIT_PEMASUKAN['JUMLAH'] and row_data[SPLIT_PEMASUKAN['JUMLAH'] - 1] else 0,
                            'keterangan': row_data[SPLIT_PEMASUKAN['KETERANGAN'] - 1] if len(row_data) >= SPLIT_PEMASUKAN['KETERANGAN'] else '',
                            'user_id': row_data[SPLIT_PEMASUKAN['OLEH'] - 1] if len(row_data) >= SPLIT_PEMASUKAN['OLEH'] else '',
                            'nama_projek': row_data[SPLIT_PEMASUKAN['PROJECT'] - 1] if len(row_data) >= SPLIT_PEMASUKAN['PROJECT'] else '',
                            'tipe': 'Pemasukan'
                        })
                    
                    if _match_message_id(mid_out, message_id):
                        row_data = sheet.row_values(row_number)
                        results.append({
                            'dompet': dompet,
                            'row': row_number,
                            'amount': int(row_data[SPLIT_PENGELUARAN['JUMLAH'] - 1]) if len(row_data) >= SPLIT_PENGELUARAN['JUMLAH'] and row_data[SPLIT_PENGELUARAN['JUMLAH'] - 1] else 0,
                            'keterangan': row_data[SPLIT_PENGELUARAN['KETERANGAN'] - 1] if len(row_data) >= SPLIT_PENGELUARAN['KETERANGAN'] else '',
                            'user_id': row_data[SPLIT_PENGELUARAN['OLEH'] - 1] if len(row_data) >= SPLIT_PENGELUARAN['OLEH'] else '',
                            'nama_projek': row_data[SPLIT_PENGELUARAN['PROJECT'] - 1] if len(row_data) >= SPLIT_PENGELUARAN['PROJECT'] else '',
                            'tipe': 'Pengeluaran'
                        })
                        
            except Exception as e:
                secure_log("WARNING", f"Error searching {dompet}: {type(e).__name__} - {str(e)}")
                continue
        
        # Search operational sheet
        try:
            op_sheet = get_or_create_operational_sheet()
            op_ids = op_sheet.col_values(OPERASIONAL_COLS['MESSAGE_ID'])
            for row_idx, mid in enumerate(op_ids):
                if _match_message_id(mid, message_id):
                    row_number = row_idx + 1
                    row_data = op_sheet.row_values(row_number)
                    results.append({
                        'dompet': OPERASIONAL_SHEET_NAME,
                        'row': row_number,
                        'amount': int(row_data[OPERASIONAL_COLS['JUMLAH'] - 1]) if len(row_data) >= OPERASIONAL_COLS['JUMLAH'] and row_data[OPERASIONAL_COLS['JUMLAH'] - 1] else 0,
                        'keterangan': row_data[OPERASIONAL_COLS['KETERANGAN'] - 1] if len(row_data) >= OPERASIONAL_COLS['KETERANGAN'] else '',
                        'user_id': row_data[OPERASIONAL_COLS['OLEH'] - 1] if len(row_data) >= OPERASIONAL_COLS['OLEH'] else '',
                        'nama_projek': 'Operasional Kantor',
                        'tipe': 'Pengeluaran'
                    })
        except Exception as e:
            secure_log("WARNING", f"Error searching operational: {type(e).__name__} - {str(e)}")
        
        return results
        
    except Exception as e:
        secure_log("ERROR", f"Find all transactions failed: {type(e).__name__} - {str(e)}")
        return []



def delete_transaction_row(dompet_sheet: str, row: int) -> bool:
    """
    Delete a transaction row from a specific sheet.
    
    Args:
        dompet_sheet: Name of the dompet sheet
        row: Row number (1-based)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if dompet_sheet == OPERASIONAL_SHEET_NAME:
            sheet = get_or_create_operational_sheet()
        else:
            sheet = get_dompet_sheet(dompet_sheet)
        
        sheet.delete_rows(row)
        secure_log("INFO", f"Transaction deleted: {dompet_sheet} row {row}")
        return True
        
    except Exception as e:
        secure_log("ERROR", f"Delete transaction error: {type(e).__name__} - {str(e)}")
        return False

def find_company_for_project(project_name: str) -> tuple:
    """
    Search all wallets to find which company contains the project history.
    Returns: (dompet_name, company_name) or (None, None)
    
    Logic:
    1. Scan all 3 wallets (Splitted Layout)
    2. Check 'Pemasukan' (Col E) and 'Pengeluaran' (Col N)
    3. If match found, return the wallet/company of that sheet.
    """
    if not project_name: return None, None
    
    clean_target = project_name.strip().lower()
    # Remove markers like (Start) or (Finish) for matching
    clean_target = clean_target.replace('(start)', '').replace('(finish)', '').strip()
    
    try:
        from config.wallets import DOMPET_SHEETS, DOMPET_COMPANIES, get_company_name_from_sheet, strip_company_prefix
        from config.constants import SPLIT_PEMASUKAN, SPLIT_PENGELUARAN, SPLIT_LAYOUT_DATA_START
        clean_target = strip_company_prefix(clean_target) or clean_target

        for dompet in DOMPET_SHEETS:
            sheet = get_dompet_sheet(dompet)
            if not sheet: continue
            
            # Optimization: We only need to check if the string exists in the column
            # Using col_values is efficient enough
            
            # 1. Check Pemasukan (Col 5 / E)
            pemasukan_projects = sheet.col_values(SPLIT_PEMASUKAN['PROJECT'])
            for p in pemasukan_projects:
                if p and clean_target in p.strip().lower():
                    # Found match!
                    comp = get_company_name_from_sheet(dompet)
                    return dompet, comp
            
            # 2. Check Pengeluaran (Col 14 / N)
            pengeluaran_projects = sheet.col_values(SPLIT_PENGELUARAN['PROJECT'])
            for p in pengeluaran_projects:
                if p and clean_target in p.strip().lower():
                    comp = get_company_name_from_sheet(dompet)
                    return dompet, comp
                    
    except Exception as e:
        secure_log("ERROR", f"find_company_for_project error: {e}")
        
    return None, None


if __name__ == '__main__':
    print("Testing Google Sheets v2.1...\n")
    
    if test_connection():
        print("\n✓ Connection successful!")
        
        # Test get categories
        print(f"\nAllowed Categories: {get_all_categories()}")
        
        # Test format data for AI
        print("\nData for AI:")
        print(format_data_for_ai(30))
