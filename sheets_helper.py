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

# Import configuration from centralized config module
from config.wallets import (
    DOMPET_SHEETS,
    DOMPET_COMPANIES,
    SELECTION_OPTIONS,
    get_dompet_for_company,
    get_selection_by_idx,
    get_available_dompets,
    # Legacy aliases
    COMPANY_SHEETS,
    FUND_SOURCES,
)

from config.constants import (
    SHEET_HEADERS,
    COL_NO, COL_TANGGAL, COL_COMPANY, COL_KETERANGAN, COL_JUMLAH,
    COL_TIPE, COL_OLEH, COL_SOURCE, COL_KATEGORI, COL_NAMA_PROJEK, COL_MESSAGE_ID,
    DASHBOARD_SHEET_NAME, SYSTEM_SHEETS,
    DEFAULT_BUDGET, BUDGET_WARNING_PERCENT,
    SPREADSHEET_ID, CREDENTIALS_FILE, SCOPES,
)

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
        # Re-raise generic exceptions so they can be caught by the caller with details
        secure_log("ERROR", f"Failed to add transaction: {type(e).__name__} - {str(e)}")
        raise


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
            # append_transaction now returns row number (truthy) or raises Exception
            if append_transaction(t, sender_name, source, 
                                  dompet_sheet=dompet_sheet, 
                                  company=company,
                                  nama_projek=nama_projek):
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
        'success': rows_added > 0,
        'rows_added': rows_added,
        'total_transactions': len(transactions),
        'errors': errors,
        'company_error': company_error
    }


def get_all_data(days: int = 30) -> List[Dict]:
    """
    Get all transaction data from ALL dompet sheets.
    Adjusted for new Wallet structure (Company in col 3).
    
    Args:
        days: Optional, only get data from last N days
        
    Returns:
        List of transaction dicts with company and nama_projek
    """
    try:
        spreadsheet = get_spreadsheet()
        
        data = []
        
        cutoff_date = None
        if days:
            cutoff_date = datetime.now() - timedelta(days=days)
        
        # Iterate over Physical Wallets (Dompet Sheets)
        for dompet in DOMPET_SHEETS:
            try:
                sheet = spreadsheet.worksheet(dompet)
                all_values = sheet.get_all_values()
                
                if len(all_values) < 2:
                    continue
                
                for row in all_values[1:]:  # Skip header
                    if len(row) < 6: # Minimal columns (No, Tgl, Comp, Ket, Jml, Tipe)
                        continue
                    
                    try:
                        # NEW Column indices (0-based from row list): 
                        # 0:No, 1:Tanggal, 2:Company, 3:Keterangan, 4:Jumlah, 5:Tipe, 
                        # 6:Oleh, 7:Source, 8:Kategori, 9:Nama Projek
                        
                        date_str = row[1] if len(row) > 1 else ''
                        if not date_str:
                            continue
                        
                        # Parse date
                        row_date = None
                        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
                            try:
                                row_date = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                        
                        if not row_date:
                            continue
                        
                        # Filter date
                        if cutoff_date and row_date < cutoff_date and row_date < datetime.now():
                            continue
                        
                        # Parse amount (Col 4)
                        amount_str = str(row[4]).replace(',', '').replace('Rp', '').replace('IDR', '').strip()
                        amount = int(float(amount_str)) if amount_str else 0
                        
                        # Parse type (Col 5)
                        tipe_raw = row[5] if len(row) > 5 else 'Pengeluaran'
                        tipe = 'Pengeluaran' if 'pengeluaran' in tipe_raw.lower() else 'Pemasukan' if 'pemasukan' in tipe_raw.lower() else tipe_raw
                        
                        # Parse Company (Col 2)
                        company = row[2].strip() if len(row) > 2 else 'Unknown'
                        if not company: company = 'Unknown'
                        
                        # Parse Params
                        keterangan = row[3] if len(row) > 3 else ''
                        oleh = row[6] if len(row) > 6 else ''
                        source = row[7] if len(row) > 7 else ''
                        kategori = row[8] if len(row) > 8 else 'Lain-lain'
                        nama_projek = row[9] if len(row) > 9 else ''

                        data.append({
                            'tanggal': date_str,
                            'keterangan': keterangan,
                            'jumlah': amount,
                            'tipe': tipe,
                            'oleh': oleh,
                            'source': source,
                            'kategori': kategori,
                            'nama_projek': nama_projek,
                            'sumber_dana': dompet,      # The physical sheet
                            'company_sheet': company    # The logical company
                        })
                    except Exception:
                        continue
                        
            except Exception as e:
                secure_log("WARNING", f"Could not read dompet {dompet}: {type(e).__name__}")
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
            
    # Group by project (Nama Projek)
    by_projek = {}
    for d in data:
        if d.get('tipe') == 'Pengeluaran':
            proj = d.get('nama_projek', '').strip()
            if proj:
                by_projek[proj] = by_projek.get(proj, 0) + d['jumlah']
    
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
            status = "UNTUNG" if profit_loss > 0 else "RUGI" if profit_loss < 0 else "NETRAL"
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
        lines.append("*Top 5 Projek (Pengeluaran):*")
        for proj, amount in sorted(s['by_projek'].items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  • {proj}: Rp {amount:,}".replace(',', '.'))
    
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
    Get cached dashboard data or calculate new summary.
    Aggregates data by Wallet (Dompet) and Company.
    """
    global _dashboard_cache, _dashboard_last_update
    
    current_time = time.time()
    
    # Return cache if valid
    if _dashboard_cache and (current_time - _dashboard_last_update) < DASHBOARD_CACHE_TTL:
        secure_log("INFO", "Using cached dashboard")
        return _dashboard_cache
    
    secure_log("INFO", "Calculating fresh dashboard summary...")
    
    try:
        # Aggregators
        total_income = 0
        total_expense = 0
        total_transactions = 0
        
        # Breakdown
        dompet_summary = {}     # {dompet_name: {'inc': 0, 'exp': 0, 'bal': 0}}
        company_summary = {}    # {company_name: {'inc': 0, 'exp': 0, 'bal': 0, 'count': 0}}
        companies_found = set()
        
        for dompet in DOMPET_SHEETS:
            try:
                # Initialize dompet stats
                dompet_summary[dompet] = {'inc': 0, 'exp': 0, 'bal': 0}
                
                sheet = get_dompet_sheet(dompet)
                all_values = sheet.get_all_values()
                
                if len(all_values) < 2:
                    continue
                
                for row in all_values[1:]:  # Skip header
                    if len(row) < 6:  # Minimal columns
                        continue
                    
                    try:
                        # Parse Fields (0-indexed)
                        # COL_COMPANY=3 -> idx 2
                        # COL_JUMLAH=5 -> idx 4
                        # COL_TIPE=6 -> idx 5
                        
                        company = row[2].strip()
                        if not company: company = "Unknown"
                        
                        raw_amount = str(row[4])
                        amount_clean = raw_amount.replace(',', '').replace('Rp', '').replace('IDR', '').strip()
                        if not amount_clean:
                            continue
                        
                        amount = int(float(amount_clean))
                        tipe = row[5].strip().lower()
                        
                        companies_found.add(company)
                        if company not in company_summary:
                            company_summary[company] = {'inc': 0, 'exp': 0, 'bal': 0, 'count': 0}
                        
                        # Fix: Include 'pengeluaran'/'pemasukan' keywords
                        is_expense = 'pengeluaran' in tipe or 'keluar' in tipe or 'withdraw' in tipe
                        is_income = 'pemasukan' in tipe or 'masuk' in tipe or 'deposit' in tipe
                        
                        total_transactions += 1
                        company_summary[company]['count'] += 1
                        
                        if is_expense:
                            total_expense += amount
                            dompet_summary[dompet]['exp'] += amount
                            company_summary[company]['exp'] += amount
                        elif is_income:
                            total_income += amount
                            dompet_summary[dompet]['inc'] += amount
                            company_summary[company]['inc'] += amount
                            
                    except (ValueError, IndexError):
                        continue
                
                # Calc balances
                dompet_summary[dompet]['bal'] = dompet_summary[dompet]['inc'] - dompet_summary[dompet]['exp']
                
            except Exception as e:
                secure_log("ERROR", f"Error processing {dompet}: {str(e)}")
                continue
        
        # Calc company balances
        for c in company_summary:
            company_summary[c]['bal'] = company_summary[c]['inc'] - company_summary[c]['exp']
        
        # Update Cache
        _dashboard_cache = {
            'total_income': total_income,
            'total_expense': total_expense,
            'balance': total_income - total_expense,
            'total_transactions': total_transactions,
            'company_count': len(companies_found),
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






if __name__ == '__main__':
    print("Testing Google Sheets v2.1...\n")
    
    if test_connection():
        print("\n✓ Connection successful!")
        
        # Test get categories
        print(f"\nAllowed Categories: {get_all_categories()}")
        
        # Test format data for AI
        print("\nData for AI:")
        print(format_data_for_ai(30))
