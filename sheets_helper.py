"""
sheets_helper.py - Google Sheets Integration Module v2.1 (Simplified)

Features:
- SINGLE Sheet architecture (no multi-sheet)
- Fixed categories (validated from security module)
- Budget Tracking & Alerts
- Report Generation
- Secure data formatting for AI

ARCHITECTURE: All transactions in ONE sheet called "Transaksi"
"""

import os
import gspread
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
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
TOKEN_FILE = 'token.json'

# Budget configuration
DEFAULT_BUDGET = int(os.getenv('DEFAULT_PROJECT_BUDGET', '10000000'))
BUDGET_WARNING_PERCENT = 80

# Scopes
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Sheet configuration - matches user's actual format
MAIN_SHEET_NAME = "Transaksi"
# User's actual column order: No, Tanggal, Keterangan, Jumlah, Tipe, Oleh, Source, Kategori
SHEET_HEADERS = ['No', 'Tanggal', 'Keterangan', 'Jumlah', 'Tipe', 'Oleh', 'Source', 'Kategori']

# Dashboard configuration
DASHBOARD_SHEET_NAME = "Dashboard"
META_SHEET_NAME = "Meta_Projek"
SYSTEM_SHEETS = {'Config', 'Template', 'Settings', 'Master', DASHBOARD_SHEET_NAME, META_SHEET_NAME}

# Global instances
_client = None
_spreadsheet = None
_main_sheet = None


def authenticate():
    """Authenticate with Google Sheets API using OAuth2."""
    global _client
    
    if _client is not None:
        return _client
    
    creds = None
    
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            pass
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        
        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"File '{CREDENTIALS_FILE}' tidak ditemukan!")
            
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            secure_log("INFO", "OAuth login required - opening browser")
            creds = flow.run_local_server(port=8888, open_browser=True)
        
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
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


def get_main_sheet():
    """Get the main transaction sheet (NO AUTO-CREATE).
    
    Raises:
        ValueError: If sheet not found - only admin can create sheets
    """
    global _main_sheet
    
    if _main_sheet is not None:
        return _main_sheet
    
    spreadsheet = get_spreadsheet()
    
    try:
        _main_sheet = spreadsheet.worksheet(MAIN_SHEET_NAME)
        secure_log("INFO", f"Using existing sheet: {MAIN_SHEET_NAME}")
    except gspread.WorksheetNotFound:
        # DO NOT CREATE - only admin can create sheets
        raise ValueError(f"Sheet '{MAIN_SHEET_NAME}' tidak ditemukan. Hubungi admin untuk membuat sheet.")
    
    return _main_sheet


def get_available_projects() -> List[str]:
    """Get list of available project sheets in the spreadsheet.
    
    Returns all sheets except system sheets (like 'Config', 'Template', etc.)
    More flexible validation - accepts any sheet with data.
    
    Returns:
        List of project/sheet names
    """
    try:
        spreadsheet = get_spreadsheet()
        all_sheets = spreadsheet.worksheets()
        
        # Debug: Log all sheets found
        all_sheet_names = [s.title for s in all_sheets]
        secure_log("INFO", f"All sheets in spreadsheet: {all_sheet_names}")
        secure_log("INFO", f"System sheets to exclude: {SYSTEM_SHEETS}")
        
        project_list = []
        for sheet in all_sheets:
            sheet_name = sheet.title
            
            # Skip system sheets
            if sheet_name in SYSTEM_SHEETS:
                secure_log("DEBUG", f"Skipping system sheet: {sheet_name}")
                continue
            
            # More flexible validation - just check if sheet has some structure
            try:
                header_row = sheet.row_values(1)
                col_count = len(header_row)
                secure_log("DEBUG", f"Sheet '{sheet_name}' has {col_count} columns: {header_row[:3]}...")
                
                # Accept sheet if it has at least 3 columns (minimal structure)
                if col_count >= 3:
                    project_list.append(sheet_name)
                    secure_log("INFO", f"✓ Added project sheet: {sheet_name}")
                else:
                    secure_log("DEBUG", f"✗ Rejected '{sheet_name}': only {col_count} columns")
            except Exception as e:
                secure_log("WARNING", f"Could not read header for {sheet_name}: {type(e).__name__}: {str(e)}")
                continue
        
        secure_log("INFO", f"Found {len(project_list)} valid project sheets: {project_list}")
        return project_list
        
    except Exception as e:
        secure_log("ERROR", f"Failed to get projects: {type(e).__name__}: {str(e)}")
        return []


def get_project_sheet(project_name: str):
    """Get a specific project sheet by name (NO AUTO-CREATE).
    
    Args:
        project_name: Name of the project/sheet to get
        
    Returns:
        gspread.Worksheet object
        
    Raises:
        ValueError: If sheet not found - only admin can create sheets
    """
    spreadsheet = get_spreadsheet()
    
    try:
        sheet = spreadsheet.worksheet(project_name)
        secure_log("INFO", f"Using project sheet: {project_name}")
        return sheet
    except gspread.WorksheetNotFound:
        # DO NOT CREATE - only admin can create sheets
        available = get_available_projects()
        available_str = ', '.join(available) if available else 'Tidak ada sheet'
        raise ValueError(
            f"Project '{project_name}' tidak ditemukan.\n"
            f"Sheet tersedia: {available_str}\n"
            f"Hubungi admin untuk membuat project baru."
        )


def get_all_categories() -> List[str]:
    """Get list of all allowed categories."""
    return ALLOWED_CATEGORIES.copy()


def append_transaction(transaction: Dict, sender_name: str, source: str = "Text", 
                       project_name: str = None) -> bool:
    """
    Append a single transaction to a project sheet.
    
    Args:
        transaction: Transaction dict with tanggal, kategori, keterangan, jumlah, tipe
        sender_name: Name of the person recording
        source: Input source (Text/Image/Voice)
        project_name: Target project/sheet name (uses main sheet if None)
    
    Transaction dict should have:
    - tanggal: YYYY-MM-DD
    - kategori: One of ALLOWED_CATEGORIES (Bahan, Alat, Operasional, Gaji)
    - keterangan: Description
    - jumlah: Amount (positive number)
    - tipe: "Pengeluaran" or "Pemasukan"
    
    Returns:
        True if successful, False otherwise
        
    Raises:
        ValueError: If project not found (NO AUTO-CREATE)
    """
    try:
        # Use project-specific sheet or fallback to main sheet
        if project_name:
            sheet = get_project_sheet(project_name)
        else:
            sheet = get_main_sheet()
        
        # Validate and sanitize category
        kategori = validate_category(transaction.get('kategori', 'Bahan'))
        
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
        
        # Calculate No (Auto-increment)
        try:
            # Check length of column B (Tanggal) to determine next number
            # If only header (1 row), len is 1, next number is 1
            # If header + 1 data (2 rows), len is 2, next number is 2
            existing_rows = len(sheet.col_values(2))
            next_no = existing_rows
        except Exception:
            next_no = 1

        # Row order matches user's spreadsheet: No, Tanggal, Keterangan, Jumlah, Tipe, Oleh, Source, Kategori
        row = [
            next_no,  # A: Auto-generated Number
            transaction.get('tanggal', datetime.now().strftime('%Y-%m-%d')),  # B: Tanggal
            keterangan,  # C: Keterangan (description)
            jumlah,  # D: Jumlah (amount)
            tipe,  # E: Tipe (Pengeluaran/Pemasukan)
            safe_sender,  # F: Oleh (recorded by)
            source,  # G: Source (Text/Image/Voice)
            kategori  # H: Kategori (LAST column!)
        ]
        
        sheet.append_row(row, value_input_option='USER_ENTERED')
        project_info = f" -> {project_name}" if project_name else ""
        secure_log("INFO", f"Transaction added{project_info}: {kategori} - {jumlah}")
        return True
        
    except ValueError as e:
        # Sheet not found error - propagate for proper handling
        secure_log("ERROR", f"Project not found: {str(e)}")
        raise
    except Exception as e:
        secure_log("ERROR", f"Failed to add transaction: {type(e).__name__}")
        return False


def append_transactions(transactions: List[Dict], sender_name: str, source: str = "Text",
                        project_name: str = None) -> Dict:
    """Append multiple transactions to a project sheet.
    
    Args:
        transactions: List of transaction dicts
        sender_name: Name of the person recording
        source: Input source (Text/Image/Voice)
        project_name: Target project/sheet name (uses main sheet if None)
        
    Returns:
        Dict with success status, rows_added count, and errors
    """
    rows_added = 0
    errors = []
    project_error = None
    
    for t in transactions:
        try:
            # Use project from transaction if available, otherwise use parameter
            target_project = t.get('project') or project_name
            if append_transaction(t, sender_name, source, project_name=target_project):
                rows_added += 1
        except ValueError as e:
            # Project not found - capture error and stop
            project_error = str(e)
            errors.append("project_not_found")
            break
        except Exception:
            errors.append("transaction_failed")
    
    return {
        'success': rows_added > 0,
        'rows_added': rows_added,
        'total_transactions': len(transactions),
        'errors': errors,
        'project_error': project_error
    }


def get_all_data(days: int = None) -> List[Dict]:
    """
    Get all transaction data from the main sheet.
    
    Args:
        days: Optional, only get data from last N days
        
    Returns:
        List of transaction dicts
    """
    try:
        sheet = get_main_sheet()
        all_values = sheet.get_all_values()
        
        if len(all_values) < 2:
            return []
        
        data = []
        
        cutoff_date = None
        if days:
            cutoff_date = datetime.now() - timedelta(days=days)
        
        for row in all_values[1:]:  # Skip header
            if len(row) < 5:
                continue
            
            try:
                # Parse date
                date_str = row[1] if len(row) > 1 else ''
                if not date_str:
                    continue
                
                try:
                    row_date = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    try:
                        row_date = datetime.strptime(date_str, '%d/%m/%Y')
                    except ValueError:
                        continue
                
                if cutoff_date and row_date < cutoff_date:
                    continue
                
                # Parse amount
                amount_str = str(row[4]).replace('.', '').replace(',', '').replace('Rp', '').strip()
                amount = int(float(amount_str)) if amount_str else 0
                
                data.append({
                    'tanggal': date_str,
                    'kategori': row[2] if len(row) > 2 else 'Lainnya',
                    'keterangan': row[3] if len(row) > 3 else '',
                    'jumlah': amount,
                    'tipe': row[5] if len(row) > 5 else 'Pengeluaran',
                    'oleh': row[6] if len(row) > 6 else '',
                    'source': row[7] if len(row) > 7 else '',
                })
            except Exception:
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
    """
    summary = get_summary(days)
    
    if summary['transaction_count'] == 0:
        return "Tidak ada data transaksi."
    
    lines = [
        f"DATA KEUANGAN ({days} HARI TERAKHIR)",
        "=" * 40,
        "",
        f"Total Pengeluaran: Rp {summary['total_pengeluaran']:,}".replace(',', '.'),
        f"Total Pemasukan: Rp {summary['total_pemasukan']:,}".replace(',', '.'),
        f"Saldo: Rp {summary['saldo']:,}".replace(',', '.'),
        f"Jumlah Transaksi: {summary['transaction_count']}",
        "",
    ]
    
    if summary['by_kategori']:
        lines.append("PER KATEGORI:")
        for kat, amount in sorted(summary['by_kategori'].items(), key=lambda x: -x[1]):
            lines.append(f"  - {kat}: Rp {amount:,}".replace(',', '.'))
        lines.append("")
    
    if summary['by_oleh']:
        lines.append("PER PENCATAT:")
        for oleh, amount in sorted(summary['by_oleh'].items(), key=lambda x: -x[1]):
            lines.append(f"  - {oleh}: Rp {amount:,}".replace(',', '.'))
    
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


# ===================== DASHBOARD FUNCTIONS =====================

def sync_project_list() -> List[str]:
    """
    Sync the Meta_Projek sheet with current project list.
    This is the source of truth for the Dashboard formulas.
    
    Returns:
        List of synced project names
    """
    try:
        spreadsheet = get_spreadsheet()
        projects = get_available_projects()
        
        # Get or create Meta sheet
        try:
            meta_sheet = spreadsheet.worksheet(META_SHEET_NAME)
        except gspread.WorksheetNotFound:
            meta_sheet = spreadsheet.add_worksheet(title=META_SHEET_NAME, rows=100, cols=10)
            meta_sheet.update('A1:C1', [['No', 'Nama Project', 'Last Sync']])
            secure_log("INFO", f"Created {META_SHEET_NAME} sheet")
        
        # Clear existing data (keep header)
        if meta_sheet.row_count > 1:
            meta_sheet.batch_clear(['A2:C100'])
        
        # Write project list
        if projects:
            sync_time = datetime.now().strftime('%Y-%m-%d %H:%M')
            rows = [[i+1, proj, sync_time] for i, proj in enumerate(projects)]
            meta_sheet.update(f'A2:C{len(rows)+1}', rows, value_input_option='USER_ENTERED')
        
        secure_log("INFO", f"Synced {len(projects)} projects to {META_SHEET_NAME}")
        return projects
        
    except Exception as e:
        secure_log("ERROR", f"Sync failed: {type(e).__name__}")
        return []


def setup_dashboard() -> bool:
    """
    Setup/update the Dashboard sheet with structure and formulas.
    Creates a professional visual dashboard that auto-updates.
    
    Returns:
        True if successful
    """
    try:
        spreadsheet = get_spreadsheet()
        
        # Ensure Meta is up to date first
        projects = sync_project_list()
        
        # Get or create Dashboard sheet
        try:
            dashboard = spreadsheet.worksheet(DASHBOARD_SHEET_NAME)
            secure_log("INFO", f"Updating existing {DASHBOARD_SHEET_NAME}")
        except gspread.WorksheetNotFound:
            dashboard = spreadsheet.add_worksheet(title=DASHBOARD_SHEET_NAME, rows=100, cols=15)
            secure_log("INFO", f"Created {DASHBOARD_SHEET_NAME} sheet")
        
        # ========== FILTER & HEADER ==========
        # B2 will be the interactive Dropdown
        header_data = [
            ['📊 DASHBOARD KEUANGAN MODERN', '', '', '', '', '', '', '', '', ''],
            ['Filter Project:', 'All Projects', '', '', f'Last Update: {datetime.now().strftime("%Y-%m-%d %H:%M")}', '', '', '', '', ''],
            ['(Ketik nama project atau "All Projects")', '', '', '', '', '', '', '', '', ''],
        ]
        
        # ========== PROJECT TABLE (DATA SOURCE) ==========
        # We build this FIRST because the summary cards will reference this table
        # This makes the "All Projects" view very fast (no recalc of 1000s of rows)
        
        project_start_row = 15  # Move table down to make room for cool cards
        project_header = [
            ['📋 DETAIL PROJECT', '', '', '', '', '', '', '', '', ''],
            ['No', 'Nama Project', 'Expense', 'Income', 'Balance', 'Trend (Daily)', 'Status', 'Tx Count', '', ''],
        ]
        
        project_rows = []
        for i, proj in enumerate(projects):
            row_num = project_start_row + 2 + i
            
            # Sparkline for Weekly Trend (Last 7 entries) - purely visual, simplified query
            # Uses QUERY to get last expenses. 
            # Note: Complex QUERY inside SPARKLINE might be heavy, so we use a simpler approach or just total bars
            # Let's use a Bar chart of Expense vs Income distribution for that project
            sparkline_formula = (
                f"=SPARKLINE(C{row_num}, "
                "{\"charttype\",\"bar\";\"max\",MAX($C$" + str(project_start_row+2) + ":$C$" + str(project_start_row+1+len(projects)) + ");\"color1\",\"#ea4335\"})"
            )
            
            # Status Indicator based on Budget (Assume 10jt default for now per project)
            status_formula = (
                f"=IF(C{row_num} > {DEFAULT_BUDGET}, \"🔴 Over\", "
                f"IF(C{row_num} > {DEFAULT_BUDGET}*0.8, \"⚠️ Warning\", \"✅ Safe\"))"
            )
            
            row = [
                i + 1,
                proj,
                f"=SUMIF('{proj}'!E:E,\"Pengeluaran\",'{proj}'!D:D)",
                f"=SUMIF('{proj}'!E:E,\"Pemasukan\",'{proj}'!D:D)",
                f'=D{row_num}-C{row_num}',
                sparkline_formula,
                status_formula,
                f"=COUNTA('{proj}'!A:A)-1",
                '', ''
            ]
            project_rows.append(row)
            
        # ========== SUMMARY CARDS (INTERACTIVE) ==========
        # Logic: If B2 is 'All Projects', Sum the table below. Else VLOOKUP the table.
        # This is SUPER efficient.
        
        range_expense = f"C{project_start_row+2}:C{project_start_row+1+len(projects)}"
        range_income  = f"D{project_start_row+2}:D{project_start_row+1+len(projects)}"
        table_range   = f"B{project_start_row+2}:H{project_start_row+1+len(projects)}"
        
        # Interactive Formulas
        f_expense = (
            f"=IF(OR(B2=\"All Projects\",B2=\"\"), SUM({range_expense}), "
            f"VLOOKUP(B2, {table_range}, 2, FALSE))"
        )
        
        f_income = (
            f"=IF(OR(B2=\"All Projects\",B2=\"\"), SUM({range_income}), "
            f"VLOOKUP(B2, {table_range}, 3, FALSE))"
        )
        
        
        f_balance = "=B6-B5" # Income - Expense
        
        # Visual Progress Bar for Budget (Global)
        # Calculates global budget vs global expense
        # Global Budget = Count(Projects) * Default
        global_budget = len(projects) * DEFAULT_BUDGET
        f_budget_progress = (
            f"=SPARKLINE(B5, {{\"charttype\",\"bar\";\"max\",IF(OR(B2=\"All Projects\",B2=\"\"),{global_budget},{DEFAULT_BUDGET});\"color1\",IF(B8>80,\"#ea4335\",\"#34a853\")}})"
        )
        
        f_percent = f"=IF(B5>0, B5/IF(OR(B2=\"All Projects\",B2=\"\"),{global_budget},{DEFAULT_BUDGET})*100, 0)"

        summary_data = [
            ['💰 EXPENSE', '💸 INCOME', '💳 NET BALANCE', '', '📊 BUDGET HEALTH', '', '', '', '', ''],
            [f_expense, f_income, f_balance, '', f_budget_progress, '', '', '', '', ''],
            ['', '', '', '', f'Usage: ', f_percent, '%', '', '', ''],
        ]

        # ========== CATEGORY BREAKDOWN (INTERACTIVE) ==========
        # This one is tricky. VLOOKUP won't work easily.
        # We will use INDIRECT for the interactive part here.
        # "If All, Sum hardcoded ranges. If specific, Sum that sheet."
        
        category_start_row = 9
        category_header = [
            ['📂 KATEGORI (Auto-Filter)', '', '', '', '', '', '', '', '', ''],
            ['Kategori', 'Total', 'Visual', '', '', '', '', '', '', ''],
        ]
        
        category_rows = []
        chart_max_range = f"B{category_start_row+2}:B{category_start_row+1+len(ALLOWED_CATEGORIES)}"
        
        for idx, cat in enumerate(ALLOWED_CATEGORIES):
            # Formula Construction
            if projects:
                # 1. Formula for "All Projects" (Sum of SUMIFS)
                all_proj_parts = []
                for proj in projects:
                    all_proj_parts.append(f"SUMIFS('{proj}'!D:D,'{proj}'!E:E,\"Pengeluaran\",'{proj}'!H:H,\"{cat}\")")
                formula_all = '=' + '+'.join(all_proj_parts)
                
                # 2. Formula for "Single Project" (INDIRECT)
                # Correct Syntax: SUMIFS(INDIRECT("'"&B2&"'!D:D"), ...)
                formula_single = (
                    f"SUMIFS(INDIRECT(\"'\"&$B$2&\"'!D:D\"),"
                    f"INDIRECT(\"'\"&$B$2&\"'!E:E\"),\"Pengeluaran\","
                    f"INDIRECT(\"'\"&$B$2&\"'!H:H\"),\"{cat}\")"
                )
                
                # Combined
                final_formula = f"=IF(OR($B$2=\"All Projects\",$B$2=\"\"), {formula_all[1:]}, {formula_single})"
            else:
                final_formula = '=0'
            
            # Sparkline Bar for category size
            cat_sparkline = (
                f"=SPARKLINE(B{category_start_row+2+idx}, "
                f"{{\"charttype\",\"bar\";\"max\",MAX({chart_max_range});\"color1\",\"#4285f4\"}})"
            )
            
            category_rows.append([
                cat,
                final_formula,
                cat_sparkline,
                '', '', '', '', '', '', ''
            ])

        # ========== WRITE ALL DATA ==========
        # Layout arrangement
        all_data = (
            header_data +        # Rows 1-3
            summary_data +       # Rows 4-6
            [['', '', '', '', '', '', '', '', '', '']] + # Spacer Row 7
            [['', '', '', '', '', '', '', '', '', '']] + # Spacer Row 8
            category_header +    # Rows 9-10
            category_rows +      # Rows 11-14 (depends on cat count)
            [['', '', '', '', '', '', '', '', '', '']] + # Spacer
            project_header +     # Row 15-16
            project_rows         # Row 17+
        )
        
        # Clear and write
        dashboard.clear()
        if all_data:
            end_row = len(all_data)
            dashboard.update(f'A1:J{end_row}', all_data, value_input_option='USER_ENTERED')
        
        try:
            # Format improvements
            dashboard.freeze(rows=2)  # Sticky Filter Row
            
            # Set widths for visual columns (Index is 1-based in gspread methods usually, let's check)
            # gspread set_column_width(col, width) where col is int (1-based)
            dashboard.set_column_width(3, 150) # Summary/Category Visuals
            dashboard.set_column_width(6, 120) # Project Trend Sparkline
            dashboard.set_column_width(2, 200) # Project Name (wide)
            
            # Auto-resize others
            # dashboard.columns_auto_resize(0, 1) # Auto resize No
        except:
            pass
        
        secure_log("INFO", f"Modern Dashboard setup complete with {len(projects)} projects")
        return True
        
    except Exception as e:
        secure_log("ERROR", f"Dashboard setup failed: {type(e).__name__}")
        return False


def get_dashboard_summary() -> Dict:
    """
    Get aggregated data from all projects for status/reporting.
    This is a programmatic way to get dashboard data without reading the sheet.
    
    Returns:
        Dict with aggregated metrics
    """
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
                
                for row in all_values[1:]:  # Skip header
                    if len(row) < 6:
                        continue
                    
                    try:
                        # Column indices for user's format: No(0), Tanggal(1), Keterangan(2), Jumlah(3), Tipe(4), Oleh(5), Source(6), Kategori(7)
                        amount_str = str(row[3]).replace('.', '').replace(',', '').replace('Rp', '').strip()
                        amount = int(float(amount_str)) if amount_str else 0
                        tipe = row[4] if len(row) > 4 else 'Pengeluaran'
                        kategori = row[7] if len(row) > 7 else ALLOWED_CATEGORIES[0]
                        
                        if tipe == 'Pengeluaran':
                            proj_expense += amount
                            total_expense += amount
                            if kategori in category_totals:
                                category_totals[kategori] += amount
                        elif tipe == 'Pemasukan':
                            proj_income += amount
                            total_income += amount
                        
                        proj_count += 1
                        total_transactions += 1
                    except:
                        continue
                
                project_data.append({
                    'name': proj,
                    'expense': proj_expense,
                    'income': proj_income,
                    'balance': proj_income - proj_expense,
                    'transactions': proj_count
                })
                
            except Exception:
                continue
        
        return {
            'total_expense': total_expense,
            'total_income': total_income,
            'balance': total_income - total_expense,
            'total_transactions': total_transactions,
            'project_count': len(projects),
            'projects': project_data,
            'by_category': category_totals,
            'budget': DEFAULT_BUDGET,
            'budget_remaining': DEFAULT_BUDGET - total_expense,
            'budget_percent': round(total_expense / DEFAULT_BUDGET * 100, 1) if DEFAULT_BUDGET > 0 else 0
        }
        
    except Exception as e:
        secure_log("ERROR", f"Get dashboard summary failed: {type(e).__name__}")
        return {
            'total_expense': 0,
            'total_income': 0,
            'balance': 0,
            'total_transactions': 0,
            'project_count': 0,
            'projects': [],
            'by_category': {},
            'budget': DEFAULT_BUDGET,
            'budget_remaining': DEFAULT_BUDGET,
            'budget_percent': 0
        }


def format_dashboard_message() -> str:
    """
    Format dashboard data as a chat message.
    Used for enhanced /status command.
    """
    data = get_dashboard_summary()
    
    # Status indicator
    if data['budget_percent'] >= 100:
        status = "🔴 OVER BUDGET"
    elif data['budget_percent'] >= 80:
        status = "🟡 WARNING"
    else:
        status = "🟢 AMAN"
    
    lines = [
        f"📊 *DASHBOARD KEUANGAN* {status}",
        "",
        f"💼 Total Project: {data['project_count']}",
        f"📝 Total Transaksi: {data['total_transactions']}",
        "",
        f"💸 Total Pengeluaran: Rp {data['total_expense']:,}".replace(',', '.'),
        f"💰 Total Pemasukan: Rp {data['total_income']:,}".replace(',', '.'),
        f"📊 Saldo Global: Rp {data['balance']:,}".replace(',', '.'),
        "",
        f"💼 Budget: Rp {data['budget']:,}".replace(',', '.'),
        f"📈 Terpakai: {data['budget_percent']:.0f}%",
        f"💵 Sisa: Rp {data['budget_remaining']:,}".replace(',', '.'),
    ]
    
    # Top projects by expense
    if data['projects']:
        lines.append("")
        lines.append("*Per Project:*")
        sorted_projects = sorted(data['projects'], key=lambda x: x['expense'], reverse=True)[:5]
        for p in sorted_projects:
            lines.append(f"  • {p['name']}: Rp {p['expense']:,}".replace(',', '.'))
    
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
