import os
import time
import gspread
import json
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from typing import List, Dict, Optional

# Load environment variables
load_dotenv()

# Import security module
from security import (
    ALLOWED_CATEGORIES,
    validate_category,
    sanitize_input,
    secure_log,
    mask_sensitive_data,
)

# Google Sheets configuration
SPREADSHEET_ID = os.getenv('GOOGLE_SHEETS_ID')
CREDENTIALS_FILE = os.getenv('CREDENTIALS_FILE', 'credentials.json')

# Budget configuration
DEFAULT_BUDGET = int(os.getenv('DEFAULT_PROJECT_BUDGET', '10000000'))
BUDGET_WARNING_PERCENT = 80

# Scopes
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Sheet configuration - Dompet sheets (3 main dompet sheets)
DOMPET_SHEETS = [
    "Dompet Holla",
    "Dompet Texturin Sby",
    "Dompet Evan"
]

# Dompet -> Companies mapping
DOMPET_COMPANIES = {
    "Dompet Holla": ["HOLLA", "HOJJA"],
    "Dompet Texturin Sby": ["TEXTURIN-Surabaya"],
    "Dompet Evan": ["TEXTURIN-Bali", "KANTOR"]
}

# Flat selection options for 1-5 display
SELECTION_OPTIONS = [
    {"idx": 1, "dompet": "Dompet Holla", "company": "HOLLA"},
    {"idx": 2, "dompet": "Dompet Holla", "company": "HOJJA"},
    {"idx": 3, "dompet": "Dompet Texturin Sby", "company": "TEXTURIN-Surabaya"},
    {"idx": 4, "dompet": "Dompet Evan", "company": "TEXTURIN-Bali"},
    {"idx": 5, "dompet": "Dompet Evan", "company": "KANTOR"},
]

# Legacy alias for backward compatibility
COMPANY_SHEETS = DOMPET_SHEETS
FUND_SOURCES = DOMPET_COMPANIES

def get_dompet_for_company(company_name: str) -> str:
    """Get the dompet (wallet) for a given company."""
    for dompet, companies in DOMPET_COMPANIES.items():
        if company_name in companies:
            return dompet
    return "Dompet Holla"  # Fallback

def get_selection_by_idx(idx: int) -> Optional[Dict]:
    """Get selection option by 1-based index."""
    for opt in SELECTION_OPTIONS:
        if opt["idx"] == idx:
            return opt
    return None

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
META_SHEET_NAME = "Meta_Projek"
SYSTEM_SHEETS = {'Config', 'Template', 'Settings', 'Master', DASHBOARD_SHEET_NAME, META_SHEET_NAME, 'Data_Agregat'}

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


def get_company_sheets() -> List[str]:
    """Get list of available company sheets.
    
    Returns:
        List of company sheet names
    """
    return COMPANY_SHEETS.copy()


def get_dompet_sheet(dompet_name: str):
    """Get a specific dompet sheet by name.
    
    Args:
        dompet_name: Name of the dompet sheet (e.g., 'Dompet Holla')
        
    Returns:
        gspread.Worksheet object
        
    Raises:
        ValueError: If sheet not found
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
        raise ValueError(
            f"Sheet '{dompet_name}' tidak ditemukan di spreadsheet.\n"
            f"Hubungi admin untuk membuat sheet."
        )


def get_company_sheet(company_name: str):
    """DEPRECATED: Use get_dompet_sheet instead.
    Kept for backward compatibility - maps company to dompet."""
    dompet = get_dompet_for_company(company_name)
    return get_dompet_sheet(dompet)


def get_available_dompets() -> List[str]:
    """Get list of available dompet sheets."""
    return DOMPET_SHEETS.copy()


def get_available_projects() -> List[str]:
    """DEPRECATED: Use get_available_dompets instead."""
    return DOMPET_SHEETS.copy()


def get_project_sheet(company_name: str):
    """DEPRECATED: Alias for get_company_sheet for backward compatibility."""
    return get_company_sheet(company_name)


def get_all_categories() -> List[str]:
    """Get list of all allowed categories."""
    return ALLOWED_CATEGORIES.copy()


def append_transaction(transaction: Dict, sender_name: str, source: str = "Text", 
                       dompet_sheet: str = None, company: str = None, 
                       nama_projek: str = None,
                       company_sheet: str = None) -> bool:
    """
    Append a single transaction to a dompet sheet.
    
    Args:
        transaction: Transaction dict with tanggal, kategori, keterangan, jumlah, tipe
        sender_name: Name of the person recording
        source: Input source (Text/Image/Voice)
        dompet_sheet: Target dompet sheet name (e.g., 'Dompet Holla')
        company: Company name (e.g., 'HOLLA', 'HOJJA', 'UMUM')
        nama_projek: Project name (REQUIRED) - use 'Saldo Umum' for wallet updates
        company_sheet: DEPRECATED - for backward compatibility, maps to dompet_sheet
    
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
        safe_company = sanitize_input(str(company or 'UMUM'))[:50]
        
        # Sanitize nama_projek (REQUIRED - default to Saldo Umum if empty)
        safe_nama_projek = sanitize_input(str(nama_projek or 'Saldo Umum'))[:100]
        
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
        secure_log("INFO", f"Transaction added to {dompet_sheet}/{safe_company}: {kategori} - {jumlah} - {safe_nama_projek}")
        
        # Return row number for revision tracking
        return row_number
        
    except ValueError as e:
        secure_log("ERROR", f"Transaction error: {str(e)}")
        raise
    except Exception as e:
        secure_log("ERROR", f"Failed to add transaction: {type(e).__name__}")
        return False


def find_transaction_by_message_id(message_id: str) -> Optional[Dict]:
    """
    Find a transaction by its MessageID across all dompet sheets.
    
    Args:
        message_id: The message ID to search for
        
    Returns:
        Dict with dompet, row, amount, keterangan, user_id if found, None otherwise
    """
    if not message_id:
        return None
    
    try:
        for dompet in DOMPET_SHEETS:
            try:
                sheet = get_dompet_sheet(dompet)
                
                # Get MessageID column (column K)
                message_ids = sheet.col_values(COL_MESSAGE_ID)
                
                # Search for the message_id
                for row_idx, mid in enumerate(message_ids):
                    if mid == message_id:
                        row_number = row_idx + 1  # 1-based row number
                        
                        # Get the row data
                        row_data = sheet.row_values(row_number)
                        
                        return {
                            'dompet': dompet,
                            'row': row_number,
                            'amount': int(row_data[COL_JUMLAH - 1]) if row_data[COL_JUMLAH - 1] else 0,
                            'keterangan': row_data[COL_KETERANGAN - 1] if len(row_data) > COL_KETERANGAN - 1 else '',
                            'user_id': row_data[COL_OLEH - 1] if len(row_data) > COL_OLEH - 1 else '',
                        }
                        
            except Exception as e:
                secure_log("WARNING", f"Error searching {dompet}: {type(e).__name__}")
                continue
        
        return None
        
    except Exception as e:
        secure_log("ERROR", f"Find transaction error: {type(e).__name__}")
        return None


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
        sheet = get_dompet_sheet(dompet_sheet)
        
        # Update the Jumlah column (column E, index 5)
        sheet.update_cell(row, COL_JUMLAH, new_amount)
        
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
        dompet_sheet: Target dompet sheet name (e.g., 'Dompet Holla')
        company: Company name (e.g., 'HOLLA', 'UMUM')
        company_sheet: DEPRECATED - for backward compatibility
        
    Returns:
        Dict with success status, rows_added count, and errors
    """
    rows_added = 0
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
            'total_transactions': len(transactions),
            'errors': ['dompet_sheet_required'],
            'company_error': 'Dompet belum dipilih'
        }
    
    for t in transactions:
        try:
            nama_projek = t.get('nama_projek', '')
            if append_transaction(t, sender_name, source, 
                                  dompet_sheet=dompet_sheet, 
                                  company=company,
                                  nama_projek=nama_projek):
                rows_added += 1
        except ValueError as e:
            company_error = str(e)
            errors.append("dompet_not_found")
            break
        except Exception:
            errors.append("transaction_failed")
    
    return {
        'success': rows_added > 0,
        'rows_added': rows_added,
        'total_transactions': len(transactions),
        'errors': errors,
        'company_error': company_error
    }


def get_all_data(days: int = None) -> List[Dict]:
    """
    Get all transaction data from ALL company sheets.
    
    Args:
        days: Optional, only get data from last N days
        
    Returns:
        List of transaction dicts with company_sheet and nama_projek
    """
    try:
        spreadsheet = get_spreadsheet()
        
        data = []
        
        cutoff_date = None
        if days:
            cutoff_date = datetime.now() - timedelta(days=days)
        
        for company in COMPANY_SHEETS:
            try:
                sheet = spreadsheet.worksheet(company)
                all_values = sheet.get_all_values()
                
                if len(all_values) < 2:
                    continue
                
                for row in all_values[1:]:  # Skip header
                    if len(row) < 5:
                        continue
                    
                    try:
                        # Column indices: No(0), Tanggal(1), Keterangan(2), Jumlah(3), Tipe(4), 
                        #                 Oleh(5), Source(6), Kategori(7), Nama Projek(8)
                        date_str = row[1] if len(row) > 1 else ''
                        if not date_str:
                            continue
                        
                        # Parse date - try multiple formats
                        row_date = None
                        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
                            try:
                                row_date = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                        
                        if not row_date:
                            continue
                        
                        # Only filter out past transactions older than cutoff
                        # Future-dated transactions are always included
                        if cutoff_date and row_date < cutoff_date and row_date < datetime.now():
                            continue
                        
                        # Parse amount
                        amount_str = str(row[3]).replace(',', '').replace('Rp', '').replace('IDR', '').strip()
                        amount = int(float(amount_str)) if amount_str else 0
                        
                        # Get type
                        tipe_raw = row[4] if len(row) > 4 else 'Pengeluaran'
                        tipe = 'Pengeluaran' if 'pengeluaran' in tipe_raw.lower() else 'Pemasukan' if 'pemasukan' in tipe_raw.lower() else tipe_raw
                        
                        # Get sumber_dana with fallback for old data
                        sumber_dana = row[9] if len(row) > 9 else ''
                        if not sumber_dana:
                             sumber_dana = get_default_fund_source(company)

                        data.append({
                            'tanggal': date_str,
                            'keterangan': row[2] if len(row) > 2 else '',
                            'jumlah': amount,
                            'tipe': tipe,
                            'oleh': row[5] if len(row) > 5 else '',
                            'source': row[6] if len(row) > 6 else '',
                            'kategori': row[7] if len(row) > 7 else 'Lain-lain',
                            'nama_projek': row[8] if len(row) > 8 else '',
                            'sumber_dana': sumber_dana,
                            'company_sheet': company
                        })
                    except Exception:
                        continue
                        
            except Exception as e:
                secure_log("WARNING", f"Could not read company {company}: {type(e).__name__}")
                continue
        
        return data
        
    except Exception as e:
        secure_log("ERROR", f"Failed to get data: {type(e).__name__}")
        return []


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
    
    return {
        'period_days': days,
        'total_pengeluaran': total_pengeluaran,
        'total_pemasukan': total_pemasukan,
        'saldo': total_pemasukan - total_pengeluaran,
        'transaction_count': len(data),
        'by_kategori': by_kategori,
        'by_oleh': by_oleh
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
    
    # Group by nama_projek - include BOTH income and expense
    by_projek = {}
    for d in data:
        projek = d.get('nama_projek', '').strip()
        if projek:
            if projek not in by_projek:
                by_projek[projek] = {'income': 0, 'expense': 0, 'company': d.get('company_sheet', '')}
            if d.get('tipe') == 'Pengeluaran':
                by_projek[projek]['expense'] += d['jumlah']
            elif d.get('tipe') == 'Pemasukan':
                by_projek[projek]['income'] += d['jumlah']
    
    if by_projek:
        lines.append("<PER_NAMA_PROJEK>")
        for projek, info in sorted(by_projek.items(), key=lambda x: -(x[1]['expense'] + x[1]['income'])):
            profit_loss = info['income'] - info['expense']
            status = "UNTUNG" if profit_loss > 0 else "RUGI" if profit_loss < 0 else "IMPAS"
            lines.append(f"  - {projek} ({info['company']}): Pemasukan={info['income']:,} | Pengeluaran={info['expense']:,} | P/L={profit_loss:,} ({status})".replace(',', '.'))
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
    
    return '\n'.join(lines)


def get_wallet_balances() -> str:
    """
    Calculate current balance for each wallet (fund source).
    Aggregates data from ALL company sheets.
    """
    # Get ALL history (no limit)
    data = get_all_data(days=None)
    
    balances = {wallet: 0 for wallet in FUND_SOURCES.keys()}
    balances["Dompet Lainnya"] = 0
    
    for d in data:
        wallet = d.get('sumber_dana', 'Dompet Lainnya')
        # Normalize wallet name safely
        if wallet not in balances:
             # Try to match partially or fallback
             found = False
             for k in balances.keys():
                 if k.lower() == str(wallet).lower():
                     wallet = k
                     found = True
                     break
             if not found:
                 # Add new wallet dynamically if found in sheet
                 balances[wallet] = 0
        
        try:
            amount = int(d['jumlah'])
            if d['tipe'] == 'Pemasukan':
                balances[wallet] += amount
            elif d['tipe'] == 'Pengeluaran':
                balances[wallet] -= amount
        except (ValueError, TypeError):
            continue
             
    # Format message
    lines = ["💰 *LAPORAN SALDO DOMPET*", "=" * 30, ""]
    
    # Sort: Defined wallets first, then others
    for wallet in FUND_SOURCES.keys():
        amount = balances.get(wallet, 0)
        lines.append(f"• {wallet}: Rp {amount:,}".replace(',', '.'))
        
    lines.append("")
    # Others
    for wallet, amount in balances.items():
        if wallet not in FUND_SOURCES and amount != 0:
            lines.append(f"• {wallet}: Rp {amount:,}".replace(',', '.'))
            
    return '\n'.join(lines)

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
DASHBOARD_CACHE_TTL = 300  # 5 minutes

def invalidate_dashboard_cache():
    """Invalidate dashboard cache (call this after adding transactions)."""
    global _dashboard_cache
    _dashboard_cache = None
    secure_log("INFO", "Dashboard cache invalidated")


def get_dashboard_summary() -> Dict:
    """
    Get financial summary across all projects.
    Uses caching (5 mins) to optimize performance.
    """
    global _dashboard_cache, _dashboard_last_update
    
    current_time = time.time()
    
    # Check cache validity
    if _dashboard_cache and (current_time - _dashboard_last_update < DASHBOARD_CACHE_TTL):
        secure_log("INFO", "Serving dashboard summary from CACHE")
        return _dashboard_cache

    secure_log("INFO", "Fetching fresh dashboard summary...")
    
    try:
        projects = get_available_projects()
        spreadsheet = get_spreadsheet()
        
        total_expense = 0
        total_income = 0
        total_transactions = 0
        project_data = []
        category_totals = {cat: 0 for cat in ALLOWED_CATEGORIES}
        
        for proj in projects:
            try:
                sheet = spreadsheet.worksheet(proj)
                all_values = sheet.get_all_values()
                
                if len(all_values) < 2:
                    continue
                
                proj_expense = 0
                proj_income = 0
                proj_count = 0
                
                secure_log("DEBUG", f"Processing {proj} - Total rows: {len(all_values)}")
                
                # Check column headers
                if len(all_values) > 0:
                     secure_log("DEBUG", f"Header: {all_values[0]}")

                for i, row in enumerate(all_values[1:]):  # Skip header
                    if len(row) < 4:  # Minimal columns
                        continue
                    
                    try:
                        # Column indices: No(0), Tanggal(1), Keterangan(2), Jumlah(3), Tipe(4), Oleh(5), Source(6), Kategori(7)
                        # Amount format: '1,500,000.00' where comma=thousands, period=decimal
                        raw_amount = str(row[3])
                        # Remove thousands separators (commas), keep decimal point
                        amount_clean = raw_amount.replace(',', '').replace('Rp', '').replace('IDR', '').strip()
                        if not amount_clean:
                            continue
                        
                        # Parse as float first (handles decimals), then convert to int
                        amount = int(float(amount_clean))
                        
                        # Robust Type Parsing
                        raw_tipe = row[4] if len(row) > 4 else 'Pengeluaran'
                        tipe = raw_tipe.lower().strip()
                        
                        kategori = row[7] if len(row) > 7 else ALLOWED_CATEGORIES[0]

                        # Type detection: check for full keywords
                        if 'pengeluaran' in tipe or 'expense' in tipe or 'keluar' in tipe:
                            proj_expense += amount
                            total_expense += amount
                            if kategori in category_totals:
                                category_totals[kategori] += amount
                        elif 'pemasukan' in tipe or 'income' in tipe or 'masuk' in tipe:
                            proj_income += amount
                            total_income += amount
                        
                        proj_count += 1
                        total_transactions += 1
                    except (ValueError, IndexError):
                        # Silently skip invalid rows
                        continue
                
                secure_log("INFO", f"Project {proj} summary: {proj_count} tx, Exp={proj_expense}, Inc={proj_income}")

                
                project_data.append({
                    'name': proj,
                    'expense': proj_expense,
                    'income': proj_income,
                    'balance': proj_income - proj_expense,
                    'count': proj_count
                })
                
            except Exception as e:
                secure_log("ERROR", f"Error processing {proj}: {str(e)}")
                continue
        
        # Update Cache
        _dashboard_cache = {
            'total_expense': total_expense,
            'total_income': total_income,
            'balance': total_income - total_expense,
            'total_transactions': total_transactions,
            'project_count': len(projects),
            'projects': project_data,
            'by_category': category_totals
        }
        _dashboard_last_update = current_time
        
        secure_log("INFO", "Dashboard cache updated")
        return _dashboard_cache
        
    except Exception as e:
        secure_log("ERROR", f"Dashboard summary failed: {type(e).__name__}")
        return {
            'total_income': 0, 'total_expense': 0, 'balance': 0,
            'total_transactions': 0, 'project_count': 0,
            'projects': [],
            'by_category': {}
        }


def format_dashboard_message() -> str:
    """
    Format dashboard data as a chat message.
    Used for enhanced /status command.
    Shows profit/loss per company instead of budget.
    """
    data = get_dashboard_summary()
    
    # Overall profit/loss indicator
    if data['balance'] > 0:
        status = "🟢 PROFIT"
    elif data['balance'] < 0:
        status = "🔴 RUGI"
    else:
        status = "⚪ IMPAS"
    
    lines = [
        f"📊 *DASHBOARD KEUANGAN* {status}",
        "",
        f"💼 Total Company: {data['project_count']}",
        f"📝 Total Transaksi: {data['total_transactions']}",
        "",
        f"💰 Total Pemasukan: Rp {data['total_income']:,}".replace(',', '.'),
        f"💸 Total Pengeluaran: Rp {data['total_expense']:,}".replace(',', '.'),
        f"📈 *Profit/Loss: Rp {data['balance']:,}*".replace(',', '.'),
    ]
    
    # Per Company Profit/Loss
    if data['projects']:
        lines.append("")
        lines.append("*Per Company:*")
        sorted_projects = sorted(data['projects'], key=lambda x: x['balance'], reverse=True)
        for p in sorted_projects:
            if p['balance'] >= 0:
                indicator = "✅" if p['balance'] > 0 else "⚪"
            else:
                indicator = "⚠️"
            lines.append(f"  {indicator} {p['name']}")
            lines.append(f"      💰 In: Rp {p['income']:,} | 💸 Out: Rp {p['expense']:,}".replace(',', '.'))
            lines.append(f"      📊 P/L: Rp {p['balance']:,}".replace(',', '.'))
    
    # Category breakdown
    if data['by_category']:
        lines.append("")
        lines.append("*Per Kategori:*")
        sorted_cats = sorted(data['by_category'].items(), key=lambda x: x[1], reverse=True)
        for cat, amount in sorted_cats:
            if amount > 0:
                lines.append(f"  • {cat}: Rp {amount:,}".replace(',', '.'))
    
    return '\n'.join(lines)



if __name__ == '__main__':
    print("Testing Google Sheets v2.1...\n")
    
    if test_connection():
        print("\n✓ Connection successful!")
        
        # Test get categories
        print(f"\nAllowed Categories: {get_all_categories()}")
        
        # Test format data for AI
        print("\nData for AI:")
        print(format_data_for_ai(30))
