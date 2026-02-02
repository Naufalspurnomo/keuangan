"""
pdf_report.py - Monthly Financial Report PDF Generator (Premium Edition)

PREMIUM FEATURES:
- A4 LANDSCAPE for maximum data visibility
- Premium cover page with gradient header + geometric accents
- Modern KPI cards with shadow/depth effects and icons
- Clean tables with subtle gradients and generous padding
- Enhanced charts with data labels and vibrant colors
- Professional header/footer with page numbers
- Polished typography and visual hierarchy

No external deps. Pure ReportLab.

Integration:
- Depend on your existing modules:
  from sheets_helper import get_all_data, COMPANY_SHEETS
  from security import ALLOWED_CATEGORIES, secure_log
"""

import os
import re
import math
import calendar
import tempfile
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

# ReportLab core
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas

from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
    Flowable,
    NextPageTemplate,
)

from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# Optional charts (still pure reportlab)
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart

# Optional font registration (still pure reportlab, but needs local .ttf files)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Import your existing modules
from sheets_helper import get_all_data, COMPANY_SHEETS
from security import ALLOWED_CATEGORIES, secure_log
from config.wallets import extract_company_prefix, strip_company_prefix


# =========================
# LOCALE
# =========================

MONTH_NAMES_ID = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember"
}


# =========================
# THEME (EXECUTIVE)
# =========================

THEME = {
    # Executive Palette - Authority & Prestige
    "primary": colors.HexColor("#0A1E36"),      # Midnight Navy (Very Dark)
    "primary_2": colors.HexColor("#1B2A41"),    # Deep Charcoal Blue
    
    # Metal Accents (Bronze/Gold)
    "accent": colors.HexColor("#C5A065"),       # Metallic Bronze/Gold (Text/Lines)
    "accent_soft": colors.HexColor("#F0E6D2"),  # Pale Champagne (Backgrounds)
    
    # Text
    "text": colors.HexColor("#2D2D2D"),         # Charcoal (Not black)
    "muted": colors.HexColor("#5A5A5A"),        # Medium Grey
    
    # Backgrounds
    "bg": colors.white,
    "bg_alt": colors.HexColor("#FAFAFA"),       # Extremely subtle grey
    "card": colors.white,
    
    # Borders - Fine Lines
    "border": colors.HexColor("#D1D1D1"),       # Light Grey
    "border_strong": colors.HexColor("#0A1E36"),# Navy for emphasis
    
    # Financial Status - classic, not "traffic light" bright
    "success": colors.HexColor("#0F5132"),      # Dark Emerald
    "danger": colors.HexColor("#842029"),       # Dark Red/Burgundy
    "neutral": colors.HexColor("#495057"),      # Dark Grey
    
    "success_bg": colors.white, 
    "danger_bg": colors.white,

    # Chart Colors - Sophisticated
    "chart_1": colors.HexColor("#0A1E36"),      # Navy
    "chart_2": colors.HexColor("#C5A065"),      # Gold
    "chart_3": colors.HexColor("#5D737E"),      # Steel Blue
    "chart_4": colors.HexColor("#8C7853"),      # Dark Bronze
}


# =========================
# THEME (HOLLAWALL STYLE)
# =========================

THEME_V2 = {
    "text": colors.HexColor("#231F20"),
    "teal": colors.HexColor("#1DB7C5"),
    "teal_soft": colors.HexColor("#18B0C0"),
    "pink": colors.HexColor("#EE396D"),
    "black": colors.HexColor("#231F20"),
}

COMPANY_THEME_V2 = {
    "Hollawall Mural": colors.HexColor("#1DB7C5"),
    "Hojja": colors.HexColor("#7A9572"),
    "Texturin Surabaya": colors.HexColor("#8C5637"),
    "Texturin Bali": colors.HexColor("#DFB281"),
}

COMPANY_ORDER_V2 = ["Hollawall Mural", "Hojja", "Texturin Surabaya", "Texturin Bali"]

OFFICE_SHEET_NAME = "Operasional Kantor"

FINISH_KEYWORDS = [
    "pelunasan", "lunas", "final payment", "penyelesaian", "selesai", "kelar", "beres", "closing"
]

# =========================
# SAFE HELPERS
# =========================

def _safe_str(v: object, default: str = "") -> str:
    if v is None:
        return default
    s = str(v)
    return s

def _to_int(v: object, default: int = 0) -> int:
    """
    Convert amount safely:
    - int/float -> int
    - "1.200.000" -> 1200000
    - "1200000" -> 1200000
    """
    if v is None:
        return default
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return default
        return int(round(v))
    s = str(v).strip()
    if not s:
        return default
    s = s.replace("Rp", "").replace("rp", "").strip()
    s = s.replace(".", "").replace(",", "")
    s = re.sub(r"[^0-9\-]", "", s)
    if not s or s == "-":
        return default
    try:
        return int(s)
    except Exception:
        return default

def format_currency(amount: int) -> str:
    return f"Rp {amount:,.0f}".replace(",", ".")

def _safe_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", name.strip())
    name = re.sub(r"_+", "_", name)
    return name.strip("_") or "report"


def format_number(amount: int) -> str:
    return f"{amount:,.0f}".replace(",", ".")


def format_period_label(year: int, month: int) -> str:
    return f"{calendar.month_abbr[month].upper()} {str(year)[-2:]}"


def format_generated_on(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now()).strftime("%d %b %y")


def _month_start_end(year: int, month: int) -> Tuple[datetime, datetime]:
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day)
    return start, end


def _prev_month(year: int, month: int) -> Tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


# =========================
# MONTH PARSER
# =========================

# Valid year range for reports
MIN_YEAR = 2020
MAX_YEAR = 2100


def parse_month_input(month_input: str) -> Tuple[int, int]:
    """
    Parse month input with validation.
    
    Supported formats:
      - "2026-01" / "2026/01"
      - "01-2026" / "01/2026"
      - "januari 2026" / "jan 2026" / "Jan 2026"
    
    Raises:
        ValueError: If format invalid, month out of range (1-12), or year out of range (2020-2100)
    """
    month_input = (month_input or "").strip().lower()
    if not month_input:
        raise ValueError("Input periode kosong. Contoh: 2026-01 atau januari 2026")

    year = None
    month = None

    # 2026-01 or 01-2026 (also with /)
    if "-" in month_input or "/" in month_input:
        sep = "-" if "-" in month_input else "/"
        parts = [p.strip() for p in month_input.split(sep) if p.strip()]
        if len(parts) == 2:
            try:
                part0 = int(parts[0])
                part1 = int(parts[1])
                
                # Determine which part is year vs month
                # If first part >= 1000, it's likely a year (YYYY-MM format)
                # Otherwise assume MM-YYYY format
                if part0 >= 1000:
                    year = part0
                    month = part1
                else:
                    month = part0
                    year = part1
            except ValueError:
                raise ValueError(f"Format tidak valid: {month_input}. Gunakan format YYYY-MM atau MM-YYYY")
    else:
        # Try month name format
        month_map = {
            "januari": 1, "jan": 1,
            "februari": 2, "february": 2, "feb": 2,
            "maret": 3, "mar": 3,
            "april": 4, "apr": 4,
            "mei": 5, "may": 5,
            "juni": 6, "jun": 6,
            "juli": 7, "jul": 7,
            "agustus": 8, "aug": 8, "ags": 8,
            "september": 9, "sep": 9,
            "oktober": 10, "okt": 10, "oct": 10,
            "november": 11, "nov": 11,
            "desember": 12, "des": 12, "dec": 12,
        }

        for key, month_num in month_map.items():
            if re.search(rf"\b{re.escape(key)}\b", month_input):
                ym = re.search(r"(\d{4})", month_input)
                if not ym:
                    raise ValueError(f"Tahun tidak ditemukan dalam input: {month_input}")
                year = int(ym.group(1))
                month = month_num
                break

    # Validate parsed values
    if year is None or month is None:
        raise ValueError(f"Format tidak dikenali: {month_input}. Contoh: 2026-01 atau januari 2026")
    
    # Validate month range
    if month < 1 or month > 12:
        raise ValueError(f"Bulan tidak valid: {month}. Harus antara 1-12")
    
    # Validate year range
    if year < MIN_YEAR or year > MAX_YEAR:
        raise ValueError(f"Tahun tidak valid: {year}. Harus antara {MIN_YEAR}-{MAX_YEAR}")

    return year, month


def validate_period_data(year: int, month: int) -> Tuple[bool, int, str]:
    """
    Validate if there's data available for the given period.
    
    Returns:
        Tuple of (has_data: bool, transaction_count: int, period_name: str)
    """
    data = get_monthly_data(year, month)
    tx_count = len(data["transactions"])
    period_name = data["period"]
    return (tx_count > 0, tx_count, period_name)


# =========================
# DATA
# =========================

def _parse_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def get_monthly_data(year: int, month: int) -> Dict:
    all_data = get_all_data()
    month_transactions: List[Dict] = []
    
    # Track all unique projects encountered in history
    all_known_projects = set()
    
    for tx in all_data:
        p = _safe_str(tx.get("nama_projek", "")).strip()
        if p:
            all_known_projects.add(p)

        date_str = _safe_str(tx.get("tanggal", "")).strip()
        dt = _parse_date(date_str)
        if dt and dt.year == year and dt.month == month:
            # normalize some keys
            tx = dict(tx)
            tx["jumlah"] = _to_int(tx.get("jumlah", 0))
            tx["company_sheet"] = _safe_str(tx.get("company_sheet", "Unknown")).strip() or "Unknown"
            tx["kategori"] = _safe_str(tx.get("kategori", "Lain-lain")).strip() or "Lain-lain"
            tx["tipe"] = _safe_str(tx.get("tipe", "Pengeluaran")).strip() or "Pengeluaran"

            nama_projek = _safe_str(tx.get("nama_projek", "")).strip()
            # IMPORTANT: nama_projek mandatory. Jika kosong, tetap tampil, tapi diberi placeholder.
            tx["nama_projek"] = nama_projek if nama_projek else "(Belum Diisi)"

            month_transactions.append(tx)

    by_company = defaultdict(list)
    by_project = defaultdict(list)

    # 1. Populate with ACTIVE transactions
    for tx in month_transactions:
        by_company[tx["company_sheet"]].append(tx)
        by_project[tx["nama_projek"]].append(tx)
        
    # 2. Backfill INACTIVE projects (Zero Reporting)
    # Ensure all historical projects appear in the list using empty tx list
    for proj in all_known_projects:
        if proj not in by_project:
            by_project[proj] = [] # Empty list = 0 income/expense

    # 3. Ensure all Company Sheets appear (Zero Reporting)
    for comp in COMPANY_SHEETS:
        if comp not in by_company:
            by_company[comp] = []

    return {
        "transactions": month_transactions,
        "by_company": dict(by_company),
        "by_project": dict(by_project),
        "period": f"{MONTH_NAMES_ID.get(month, str(month))} {year}",
        "year": year,
        "month": month,
    }

def calculate_pnl(transactions: List[Dict]) -> Dict:
    income = 0
    expense = 0
    by_category = {cat: 0 for cat in ALLOWED_CATEGORIES}
    by_category.setdefault("Lain-lain", 0)

    expense_transactions = []
    income_transactions = []

    for tx in transactions:
        amount = _to_int(tx.get("jumlah", 0))
        tipe = _safe_str(tx.get("tipe", "Pengeluaran")).lower()
        category = _safe_str(tx.get("kategori", "Lain-lain")).strip() or "Lain-lain"

        is_income = ("pemasukan" in tipe) or ("income" in tipe)
        if is_income:
            income += amount
            income_transactions.append(tx)
        else:
            expense += amount
            expense_transactions.append(tx)
            if category in by_category:
                by_category[category] += amount
            else:
                by_category["Lain-lain"] += amount

    expense_transactions.sort(key=lambda x: _to_int(x.get("jumlah", 0)), reverse=True)
    income_transactions.sort(key=lambda x: _to_int(x.get("jumlah", 0)), reverse=True)

    return {
        "income": income,
        "expense": expense,
        "profit": income - expense,
        "by_category": by_category,
        "expense_transactions": expense_transactions,
        "income_transactions": income_transactions,
    }


# =========================
# DATA (HOLLAWALL STYLE)
# =========================

def _normalize_tx(tx: Dict) -> Optional[Dict]:
    date_str = _safe_str(tx.get("tanggal", "")).strip()
    dt = _parse_date(date_str)
    if not dt:
        return None
    return {
        "tanggal": date_str,
        "dt": dt,
        "keterangan": _safe_str(tx.get("keterangan", "")).strip(),
        "jumlah": _to_int(tx.get("jumlah", 0)),
        "tipe": _safe_str(tx.get("tipe", "Pengeluaran")).strip(),
        "kategori": _safe_str(tx.get("kategori", "Lain-lain")).strip() or "Lain-lain",
        "company_sheet": _safe_str(tx.get("company_sheet", "Unknown")).strip(),
        "nama_projek": _safe_str(tx.get("nama_projek", "")).strip(),
    }


def _get_all_transactions_v2() -> List[Dict]:
    all_data = get_all_data(days=None)
    normalized = []
    for tx in all_data:
        ntx = _normalize_tx(tx)
        if ntx:
            normalized.append(ntx)
    return normalized


def _filter_period(transactions: List[Dict], start_dt: datetime, end_dt: datetime) -> List[Dict]:
    out = []
    for tx in transactions:
        dt = tx.get("dt")
        if not dt:
            continue
        if start_dt <= dt <= end_dt:
            out.append(tx)
    return out


def _is_income(tx: Dict) -> bool:
    return "pemasukan" in tx.get("tipe", "").lower()


def _is_expense(tx: Dict) -> bool:
    return not _is_income(tx)


def _is_salary(tx: Dict) -> bool:
    category = (tx.get("kategori") or "").lower()
    desc = (tx.get("keterangan") or "").lower()
    return "gaji" in category or "gaji" in desc


def _company_from_tx(tx: Dict) -> Optional[str]:
    dompet = tx.get("company_sheet")
    if dompet == "TX SBY(216)":
        return "Texturin Surabaya"
    if dompet == "TX BALI(087)":
        return "Texturin Bali"
    if dompet == "CV HB (101)":
        prefix = extract_company_prefix(tx.get("nama_projek", ""))
        if prefix == "HOJJA":
            return "Hojja"
        return "Hollawall Mural"
    return None


def _summarize_period(transactions: List[Dict]) -> Dict:
    income_total = 0
    expense_total = 0
    office_expense = 0
    for tx in transactions:
        amt = tx.get("jumlah", 0)
        if _is_income(tx):
            income_total += amt
        else:
            expense_total += amt
            if tx.get("company_sheet") == OFFICE_SHEET_NAME:
                office_expense += amt
    return {
        "income_total": income_total,
        "expense_total": expense_total,
        "office_expense": office_expense,
        "profit": income_total - expense_total,
    }


def _pct_change(curr: int, prev: int) -> Optional[int]:
    if prev == 0:
        if curr == 0:
            return 0
        return None
    return int(round(((curr - prev) / prev) * 100))


def _insight_text(label: str, curr: int, prev: int) -> str:
    pct = _pct_change(curr, prev)
    if pct is None:
        return "Naik signifikan"
    if label == "expense":
        if pct < 0:
            return f"Menurun {abs(pct)}%"
        if pct > 0:
            return f"Meningkat {pct}%"
        return "Stabil"
    if label == "profit" and curr < 0:
        return "Merugi"
    if pct > 0:
        return f"Wah meningkat {pct}%"
    if pct < 0:
        return f"Menurun {abs(pct)}%"
    return "Stabil"


def _finished_projects_by_company(period_txs: List[Dict]) -> Dict[str, List[str]]:
    finished = {c: set() for c in COMPANY_ORDER_V2}
    for tx in period_txs:
        if not _is_income(tx):
            continue
        desc = (tx.get("keterangan") or "").lower()
        if not any(k in desc for k in FINISH_KEYWORDS):
            continue
        proj = tx.get("nama_projek", "").strip()
        if not proj:
            continue
        comp = _company_from_tx(tx)
        if comp in finished:
            finished[comp].add(proj)
    return {k: sorted(list(v)) for k, v in finished.items()}


def _project_metrics(project_txs: List[Dict]) -> Dict:
    dp = dp2 = pelunasan = 0
    total_income = 0
    total_expense = 0
    total_salary = 0
    for tx in project_txs:
        amt = tx.get("jumlah", 0)
        desc = (tx.get("keterangan") or "").lower()
        if _is_income(tx):
            total_income += amt
            if "dp2" in desc or "dp 2" in desc:
                dp2 += amt
            elif "dp" in desc:
                dp += amt
            elif any(k in desc for k in FINISH_KEYWORDS):
                pelunasan += amt
        else:
            total_expense += amt
            if _is_salary(tx):
                total_salary += amt
    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "total_salary": total_salary,
        "dp": dp,
        "dp2": dp2,
        "pelunasan": pelunasan,
        "profit": total_income - total_expense,
    }

# =========================
# FONTS (OPTIONAL)
# =========================

def register_fonts() -> Dict[str, str]:
    """
    Optional: place fonts in ./assets/fonts/
      - Inter-Regular.ttf
      - Inter-SemiBold.ttf
      - Inter-Bold.ttf   (optional)
    If missing, fallback to Helvetica.

    Returns dict: {"regular": "...", "semibold": "...", "bold": "..."}
    """
    base_dir = os.path.dirname(__file__)
    font_dir = os.path.join(base_dir, "assets", "fonts")

    candidates = {
        "regular": ("Inter", os.path.join(font_dir, "Inter-Regular.ttf")),
        "semibold": ("Inter-SemiBold", os.path.join(font_dir, "Inter-SemiBold.ttf")),
        "bold": ("Inter-Bold", os.path.join(font_dir, "Inter-Bold.ttf")),
    }

    ok = True
    for _, (_, path) in candidates.items():
        if not os.path.exists(path):
            ok = False
            break

    if ok:
        try:
            for key, (name, path) in candidates.items():
                pdfmetrics.registerFont(TTFont(name, path))
            return {"regular": "Inter", "semibold": "Inter-SemiBold", "bold": "Inter-Bold"}
        except Exception:
            pass

    return {"regular": "Helvetica", "semibold": "Helvetica-Bold", "bold": "Helvetica-Bold"}


# =========================
# STYLES
# =========================

def create_styles(fonts: Dict[str, str]):
    """
    Create Executive paragraph styles.
    Typography: Serif headers (Times), Sans-Serif body (Helvetica).
    """
    styles = getSampleStyleSheet()

    # Body - Clean Sans-Serif
    styles["Normal"].fontName = "Helvetica"
    styles["Normal"].fontSize = 9
    styles["Normal"].leading = 13
    styles["Normal"].textColor = THEME["text"]
    styles["Normal"].alignment = TA_LEFT

    # Muted Text for labels/metadata
    styles.add(ParagraphStyle(
        name="Muted",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=THEME["muted"],
    ))

    # H1 - Executive Title (Serif)
    styles.add(ParagraphStyle(
        name="H1",
        parent=styles["Normal"],
        fontName="Times-Bold",  # SERIF for prestige
        fontSize=16,
        leading=20,
        textColor=THEME["primary"],
        spaceBefore=16,
        spaceAfter=8,
        textTransform="uppercase", 
    ))

    # H2 - Section Header (Serif)
    styles.add(ParagraphStyle(
        name="H2",
        parent=styles["Normal"],
        fontName="Times-Bold",
        fontSize=12,
        leading=14,
        textColor=THEME["primary_2"],
        spaceBefore=12,
        spaceAfter=6,
    ))

    # Section divider label - All caps sans-serif
    styles.add(ParagraphStyle(
        name="SectionTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=THEME["accent"],
        spaceBefore=12,
        spaceAfter=4,
        textTransform="uppercase",
        borderWidth=0,
    ))
    
    # Financial Value (Serif for numbers looks classic "Accounting")
    styles.add(ParagraphStyle(
        name="BigValue",
        parent=styles["Normal"],
        fontName="Times-Bold",
        fontSize=20,
        leading=24,
        textColor=THEME["primary"],
        alignment=TA_LEFT,
    ))
    
    # Label
    styles.add(ParagraphStyle(
        name="Label",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=THEME["muted"],
        textTransform="uppercase",
        alignment=TA_LEFT,
    ))

    return styles


# =========================
# UI FLOWABLES (CORPORATE)
# =========================

class Divider(Flowable):
    def __init__(self, width: float, thickness: float = 0.5, color=THEME["border"], space_before=4, space_after=8):
        super().__init__()
        self.width = width
        self.thickness = thickness
        self.color = color
        self.space_before = space_before
        self.space_after = space_after

    def wrap(self, availWidth, availHeight):
        return (self.width, self.space_before + self.thickness + self.space_after)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setStrokeColor(self.color)
        c.setLineWidth(self.thickness)
        y = self.space_after + self.thickness / 2.0
        c.line(0, y, self.width, y)
        c.restoreState()


class FinancialSummary(Flowable):
    """
    Executive financial summary block.
    Style: Minimalist, Serif numbers, Gold accent lines.
    """
    def __init__(self, items: List[Dict], width: float, height: float = 24 * mm):
        super().__init__()
        self.items = items
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        
        # Draw top and bottom double borders (Accounting Style)
        # Top Line (Thick Navy)
        c.setStrokeColor(THEME["primary"])
        c.setLineWidth(1.5)
        c.line(0, self.height, self.width, self.height)
        
        # Bottom Line (Thin Gold/Bronze)
        c.setStrokeColor(THEME["accent"])
        c.setLineWidth(1)
        c.line(0, 0, self.width, 0)

        n = len(self.items)
        col_width = self.width / n
        
        for i, item in enumerate(self.items):
            x = i * col_width
            
            # Vertical separator (Short, Gold)
            if i < n - 1:
                c.setStrokeColor(THEME["accent"])
                c.setLineWidth(0.5)
                # Centered vertically, not full height
                sep_h = self.height * 0.4
                sep_y = (self.height - sep_h) / 2
                c.line(x + col_width, sep_y, x + col_width, sep_y + sep_h)

            # --- Content ---
            
            # Label (Upper, Sans-Serif, Spaced)
            c.setFillColor(THEME["muted"])
            c.setFont("Helvetica", 7)
            label = item.get("title", "").upper()
            # Tracking/Spacing logic omitted for simplicity, just clean text
            c.drawString(x + 10, self.height - 12, label)
            
            # Value (Large, Serif, Primary Color)
            val_color = THEME["primary"]
            tone = item.get("tone", "neutral")
            
            # In executive reports, we don't use red/green for main numbers often, 
            # maybe just for the profit margin. Let's keep numbers Navy unless negative.
            if tone == "danger": val_color = THEME["danger"]
            
            c.setFillColor(val_color)
            c.setFont("Times-Bold", 16) # Serif for numbers
            c.drawString(x + 10, 8, _safe_str(item.get("value", "")))

        c.restoreState()


def create_financial_summary(income: int, expense: int, profit: int, width: float) -> FinancialSummary:
    profit_tone = "neutral" if profit >= 0 else "danger"
    items = [
        {"title": "Total Revenue", "value": format_currency(income), "tone": "neutral"},
        {"title": "Total Expenses", "value": format_currency(expense), "tone": "neutral"},
        {"title": "Net Profit", "value": format_currency(profit), "tone": profit_tone},
    ]
    return FinancialSummary(items, width=width)



# =========================
# TABLES (EXECUTIVE ACCOUNTING STYLE)
# =========================

def create_data_table(
    headers: List[str],
    rows: List[List],
    col_widths: Optional[List[float]] = None,
    right_cols: Optional[List[int]] = None,
    fonts: Optional[Dict[str, str]] = None,
    has_total_row: bool = False,
) -> Table:
    """
    Create Executive 'Accounting Style' table.
    Characteristics: Open sides, strong header/bottom lines, double line for totals.
    """
    fonts = fonts or {"regular": "Helvetica", "semibold": "Helvetica-Bold", "bold": "Helvetica-Bold"}
    right_cols = set(right_cols or [])

    # Base style for table cells
    base = getSampleStyleSheet()["Normal"]
    base.fontName = "Helvetica"
    base.fontSize = 9
    base.leading = 12
    base.textColor = THEME["text"]

    def P(text: str, bold: bool = False, color=None, align=None):
        f = fonts["bold"] if bold else fonts["regular"]
        col = color if color is not None else THEME["text"]
        t = _safe_str(text)
        return Paragraph(f'<font name="{f}" color="{col}">{t}</font>', base)

    # 1. Header Row
    # Uppercase, Serif-Bold for headers to match the document theme
    header_para = [
        Paragraph(f'<font name="Times-Bold" size=9 color="{THEME["primary"].hexval()}">{h.upper()}</font>', base)
        for h in headers
    ]
    data = [header_para]

    # 2. Data Rows
    for i, r in enumerate(rows):
        is_last = (i == len(rows) - 1)
        row_cells = []
        for j, cell in enumerate(r):
            if hasattr(cell, 'wrap'):
                row_cells.append(cell)
            else:
                # If total row (last row) + has_total_row flag
                is_total_cell = (has_total_row and is_last)
                
                # Logic for bolding: if total row, bold everything
                should_bold = is_total_cell
                
                # Logic for text color
                txt_color = THEME["text"]
                if is_total_cell:
                    txt_color = THEME["primary"] # Navy for totals
                
                row_cells.append(P(cell, bold=should_bold, color=txt_color))
        data.append(row_cells)

    t = Table(data, colWidths=col_widths)

    # 3. Styling Commands
    style_cmds = [
        # --- Header ---
        # Top line (Thick)
        ("LINEABOVE", (0, 0), (-1, 0), 1.5, THEME["primary"]),
        # Bottom of header (Thin)
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, THEME["primary"]),
        # Background: None (Clean white)
        
        # --- Body ---
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        
        # Grid: Open sides
        # No vertical grid.
        # No horizontal grid inside body (clean).
    ]
    
    # If we have a total row, add specific styling
    if has_total_row:
        # Line above Top Row (Single)
        style_cmds.append(("LINEABOVE", (0, -1), (-1, -1), 0.5, THEME["text"]))
        # Line below Total Row (Double - Accounting Standard)
        # ReportLab doesn't support 'double', so we simulate or use a thick line
        # Using a thick bottom line is a common proxy
        style_cmds.append(("LINEBELOW", (0, -1), (-1, -1), 1.5, THEME["primary"]))
    else:
        # Standard bottom line
        style_cmds.append(("LINEBELOW", (0, -1), (-1, -1), 0.5, THEME["border"]))

    # zebra striping? Executive reports often avoid it for pure white, 
    # but very subtle is okay. Let's skip it for "Accounting" look.

    # Alignment
    style_cmds.append(("ALIGN", (0, 0), (-1, -1), "LEFT"))
    for col in right_cols:
        style_cmds.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))

    t.setStyle(TableStyle(style_cmds))
    return t


# =========================
# SPECIFIC TABLES (DYNAMIC)
# =========================

def create_pnl_table(consolidated_pnl: Dict, fonts: Dict[str, str], width: float = 0) -> Table:
    """
    Consolidated P&L Table (High-End Accounting Style).
    Dynamic width: ~55% Desc, ~25% Amount, ~20% %Rev.
    """
    # Default to 18cm if 0 passed
    if width <= 0: width = 18*cm
    
    # Ratios
    w_desc = width * 0.55
    w_amt = width * 0.25
    w_pct = width * 0.20
    
    headers = ["DESCRIPTION", "AMOUNT", "% REV"]
    rows = []
    
    # helper for clean values
    def fmt(n): return format_currency(n)
    
    # 1. INCOME
    rows.append(["REVENUE", "", ""])
    rows.append(["  Total Revenue", fmt(consolidated_pnl["income"]), "100.0%"])
    rows.append(["", "", ""]) # Spacer
    
    # 2. EXPENSES
    rows.append(["OPERATING EXPENSES", "", ""])
    
    total_inc = consolidated_pnl["income"] if consolidated_pnl["income"] != 0 else 1 # Avoid div/0
    
    sorted_cats = sorted(consolidated_pnl["by_category"].items(), key=lambda x: x[1], reverse=True)
    
    for cat, amt in sorted_cats:
        if amt == 0: continue
        pct = (amt / total_inc * 100)
        rows.append([f"  {cat}", fmt(amt), f"{pct:.1f}%"])
        
    total_exp = consolidated_pnl["expense"]
    rows.append(["  Total Operating Expenses", fmt(total_exp), f"{(total_exp/total_inc*100):.1f}%"])
    rows.append(["", "", ""]) # Spacer

    # 3. NET PROFIT
    net_profit = consolidated_pnl["profit"]
    net_margin = (net_profit / total_inc * 100)
    
    rows.append(["NET PROFIT (LOSS)", fmt(net_profit), f"{net_margin:.1f}%"])
    
    # Create Table
    t = create_data_table(
        headers=headers,
        rows=rows,
        col_widths=[w_desc, w_amt, w_pct],
        right_cols=[1, 2],
        fonts=fonts,
        has_total_row=False
    )
    
    # apply specific P&L styles (bolding headers/totals)
    style_opts = [
        # Headers
        ("FONTNAME", (0, 1), (0, 1), "Times-Bold"), # REVENUE
        ("FONTNAME", (1, 2), (2, 2), "Times-Bold"), # Total Rev
        ("FONTNAME", (0, 4), (0, 4), "Times-Bold"), # OP EXPENSES
        
        # Total Expense (Find by negative index relative to end)
        ("FONTNAME", (1, -3), (2, -3), "Times-Bold"),
        ("LINEABOVE", (1, -3), (2, -3), 0.5, THEME["text"]), 
        
        # Net Profit
        ("FONTNAME", (0, -1), (-1, -1), "Times-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1), THEME["primary"] if net_profit >= 0 else THEME["danger"]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, THEME["text"]),
        ("LINEBELOW", (0, -1), (-1, -1), 1.5, THEME["primary"]),
    ]
    
    t.setStyle(TableStyle(style_opts))
    return t


def create_project_summary_table(project_summaries: List[Dict], fonts: Dict[str, str], width: float = 0) -> Table:
    """
    Executive project summary table.
    Dynamic column adjustment.
    """
    if width <= 0: width = 18*cm
    
    # Columns: Name (40%), Income (15%), Expense (15%), Profit (20%), Margin (10%)
    # Adjusted for realistic lengths
    w_name = width * 0.38
    w_inc = width * 0.17
    w_exp = width * 0.17
    w_prof = width * 0.18
    w_marg = width * 0.10
    
    headers = ["PROJECT NAME", "INCOME", "EXPENSE", "PROFIT", "MG%"]
    rows = []
    
    sorted_projects = sorted(project_summaries, key=lambda x: x["profit"], reverse=True)
    
    total_income = sum(p["income"] for p in sorted_projects)
    total_expense = sum(p["expense"] for p in sorted_projects)
    total_profit = sum(p["profit"] for p in sorted_projects)
    total_margin = (total_profit / total_income * 100) if total_income > 0 else 0

    for p in sorted_projects:
        profit = p["profit"]
        income = p["income"]
        margin = (profit / income * 100) if income > 0 else 0
        
        # Color the profit text? Or just formatting? 
        # Executive style: Parentheses for negative is cleaner, but let's stick to standard signs + conditional color.
        # Actually create_data_table handles row-by-row rendering generically.
        # For explicit coloring, we need Paragraphs (Flowables).
        # Let's keep it simple string for now, create_data_table handles safety.
        
        row_cells = [
            _safe_str(p["name"])[:40], # Safety truncate
            format_currency(int(p["income"])),
            format_currency(int(p["expense"])),
            format_currency(int(p["profit"])),
            f"{margin:.1f}%",
        ]
        rows.append(row_cells)

    # Total Row
    rows.append([
        "TOTAL",
        format_currency(total_income),
        format_currency(total_expense),
        format_currency(total_profit),
        f"{total_margin:.1f}%"
    ])

    t = create_data_table(
        headers=headers,
        rows=rows,
        col_widths=[w_name, w_inc, w_exp, w_prof, w_marg],
        right_cols=[1, 2, 3, 4],
        fonts=fonts,
        has_total_row=True,
    )
    
    return t


# =========================
# CHART (EXECUTIVE MINIMALIST)
# =========================

def create_expense_category_chart(by_category: Dict[str, int], width: float = 18*cm, height: float = 6*cm) -> Drawing:
    """
    Executive vertical bar chart.
    Minimalist: No strokes on bars, simple text.
    """
    items = [(cat, _to_int(by_category.get(cat, 0))) for cat in ALLOWED_CATEGORIES]
    
    labels = [k[:12] for k, _ in items]
    values = [v for _, v in items]
    
    d = Drawing(width, height)
    
    bc = VerticalBarChart()
    bc.x = 40
    bc.y = 20
    bc.width = width - 50
    bc.height = height - 20 # Maximize height
    bc.data = [values]
    
    # Y-Axis (Value)
    bc.valueAxis.valueMin = 0
    bc.valueAxis.labelTextFormat = lambda x: f"{x/1000000:.1f}M" if abs(x) >= 1000000 else f"{x/1000:.0f}K"
    bc.valueAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.labels.fillColor = THEME["muted"]
    bc.valueAxis.gridStrokeWidth = 0.5 # Minimal grid
    bc.valueAxis.gridStrokeColor = colors.HexColor("#EEEEEE")
    bc.valueAxis.visibleGrid = 1
    bc.valueAxis.visibleAxis = 0 # Hide y-axis line
    
    # X-Axis (Category)
    bc.categoryAxis.categoryNames = labels
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontSize = 7
    bc.categoryAxis.labels.fillColor = THEME["text"]
    bc.categoryAxis.labels.angle = 0
    bc.categoryAxis.visibleAxis = 1
    bc.categoryAxis.strokeColor = THEME["border"]
    
    # Colors
    chart_colors = [THEME["chart_1"], THEME["chart_2"], THEME["chart_3"], THEME["chart_4"]]
    for i in range(len(items)):
        bc.bars[(0, i)].fillColor = chart_colors[i % len(chart_colors)]
    
    bc.bars.strokeWidth = 0
    bc.barSpacing = 6
    
    d.add(bc)
    return d


def create_project_profit_chart(project_summaries: List[Dict], width: float = 18*cm, height: float = 6*cm) -> Drawing:
    """
    Executive horizontal bar chart.
    Clean, no axis labels (direct labeling).
    """
    # Top 8
    items = sorted(project_summaries, key=lambda x: x.get('profit', 0), reverse=True)[:8]
    if not items:
        return Drawing(width, 10)

    # Reverse for horizontal chart
    items = list(reversed(items))
    
    labels = [_safe_str(p.get('name', ''))[:20] for p in items]
    values = [p.get('profit', 0) for p in items]
    
    d = Drawing(width, height)
    
    from reportlab.graphics.charts.barcharts import HorizontalBarChart
    
    chart_left = 10
    chart_right = width - 10
    
    bc = HorizontalBarChart()
    bc.x = chart_left
    bc.y = 5
    bc.width = chart_right - chart_left
    bc.height = height - 10
    bc.data = [values]
    
    # Hide Axes (We use direct labels)
    bc.valueAxis.visible = 0
    bc.categoryAxis.visible = 0
    
    bc.bars.strokeWidth = 0
    bc.barSpacing = 4
    
    # Color logic
    for i, val in enumerate(values):
        bc.bars[(0, i)].fillColor = THEME["chart_3"] if val >= 0 else THEME["danger"]
    
    d.add(bc)
    
    # Direct Labeling (Inside or Next to Bar)
    n_bars = len(values)
    bar_h = (height - 10) / n_bars
    
    for i, (label, val) in enumerate(zip(labels, values)):
        y_center = 5 + (i + 0.5) * bar_h
        
        # Label (Left aligned at start of bar area)
        d.add(String(chart_left, y_center + 4, label, fontName="Helvetica", fontSize=8, fillColor=THEME["text"], textAnchor="start"))
        
        # Value (Right aligned at end of bar area)
        val_txt = format_currency(val)
        d.add(String(chart_right, y_center + 4, val_txt, fontName="Helvetica-Bold", fontSize=8, fillColor=THEME["primary"], textAnchor="end"))
    
    return d


def create_project_profit_chart(project_summaries: List[Dict], width: float = 17*cm, height: float = 5*cm) -> Drawing:
    """
    Horizontal bar chart: Profit by project.
    Sorted by profit (highest at top). Green for profit, red for loss.
    Labels: LEFT for positive bars (going right), RIGHT for negative bars (going left).
    """
    # Sort by profit descending (highest profit at top of chart = first in reversed list)
    items = sorted(project_summaries, key=lambda x: x.get('profit', 0), reverse=True)[:8]
    
    if not items:
        d = Drawing(width, height)
        d.add(String(width/2, height/2, "No data", fontSize=10, fillColor=THEME["muted"], textAnchor="middle"))
        return d
    
    # Reverse for horizontal bar (top of chart = last item in data)
    items = list(reversed(items))
    
    labels = [_safe_str(p.get('name', ''))[:14] for p in items]
    values = [p.get('profit', 0) for p in items]
    
    d = Drawing(width, height)
    
    # Title
    d.add(String(0, height - 10, "Profit per Projek", fontSize=9, fillColor=THEME["muted"]))
    
    from reportlab.graphics.charts.barcharts import HorizontalBarChart
    
    # Chart area
    chart_left = 90  # Room for positive labels on left
    chart_right = width - 90  # Room for negative labels on right
    chart_y = 8
    chart_height = height - 25
    
    bc = HorizontalBarChart()
    bc.x = chart_left
    bc.y = chart_y
    bc.width = chart_right - chart_left
    bc.height = chart_height
    bc.data = [values]
    
    # Handle negative values
    min_val = min(values) if values else 0
    max_val = max(values) if values else 0
    bc.valueAxis.valueMin = min(0, min_val * 1.2) if min_val < 0 else 0
    bc.valueAxis.valueMax = max_val * 1.1 if max_val > 0 else 1000000
    bc.valueAxis.labelTextFormat = lambda x: f"{x/1000000:.1f}M" if abs(x) >= 1000000 else f"{x/1000:.0f}K"
    bc.valueAxis.labels.fontSize = 7
    
    # Hide default category axis labels (we'll draw our own)
    bc.categoryAxis.categoryNames = [""] * len(labels)  # Empty labels
    bc.categoryAxis.labels.fontSize = 1
    bc.categoryAxis.labels.visible = 0
    
    # Default bar styling
    bc.bars.strokeWidth = 0
    bc.barSpacing = 3
    
    # Color each bar based on profit/loss
    for i, val in enumerate(values):
        if val >= 0:
            bc.bars[(0, i)].fillColor = THEME["success"]
        else:
            bc.bars[(0, i)].fillColor = THEME["danger"]
    
    d.add(bc)
    
    # Manually draw labels
    n_bars = len(values)
    bar_height = chart_height / n_bars if n_bars > 0 else 10
    
    for i, (label, val) in enumerate(zip(labels, values)):
        y_pos = chart_y + (i + 0.5) * bar_height  # Center of bar
        
        if val >= 0:
            # Label on LEFT (before the bar)
            d.add(String(chart_left - 5, y_pos - 3, label, 
                        fontSize=8, fillColor=THEME["text"], textAnchor="end"))
        else:
            # Label on RIGHT (after the bar end)
            d.add(String(chart_right + 5, y_pos - 3, label, 
                        fontSize=8, fillColor=THEME["danger"], textAnchor="start"))
    
    return d


# =========================
# DOCUMENT TEMPLATE (PREMIUM A4 LANDSCAPE)
# =========================

# A4 Landscape dimensions
A4_LANDSCAPE = (A4[1], A4[0])  # Swap width and height

# =========================
# DOCUMENT TEMPLATE (EXECUTIVE)
# =========================

def draw_header_footer(canvas, doc, period_text: str, title_text: str):
    """
    High-End Executive Letterhead.
    Mix of Serif authority and Gold accents.
    """
    canvas.saveState()
    
    # --- HEADER ---
    header_top = A4[1] - 1.5*cm
    
    # 1. Branding Bar (Gold/Accent) - Small top strip
    canvas.setFillColor(THEME["accent"])
    canvas.rect(0, A4[1] - 0.4*cm, A4[0], 0.4*cm, fill=1, stroke=0)
    
    # 2. Company/Report Title (Serif, Large, Navy)
    canvas.setFillColor(THEME["primary"])
    canvas.setFont("Times-Bold", 18)
    canvas.drawString(doc.leftMargin, header_top, "FINANCE BOT REPORT")
    
    # 3. Period/Date (Sans-Serif, Muted)
    canvas.setFillColor(THEME["muted"])
    canvas.setFont("Helvetica", 10)
    canvas.drawString(doc.leftMargin, header_top - 14, f"Period: {period_text}")
    
    # 4. "CONFIDENTIAL" Label (Right aligned, red/accent?)
    canvas.setFillColor(THEME["danger"]) # Or Neutral
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawRightString(A4[0] - doc.rightMargin, header_top + 4, "STRICTLY PRIVATE & CONFIDENTIAL")
    
    # 5. Divider Line (Navy, thick)
    canvas.setStrokeColor(THEME["primary"])
    canvas.setLineWidth(2)
    canvas.line(doc.leftMargin, header_top - 20, A4[0] - doc.rightMargin, header_top - 20)
    
    # --- FOOTER ---
    footer_y = 1.5*cm
    
    # 1. Top Footer Line (Thin Gold)
    canvas.setStrokeColor(THEME["accent"])
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, footer_y + 10, A4[0] - doc.rightMargin, footer_y + 10)
    
    # 2. Disclaimer Text
    canvas.setFillColor(THEME["muted"])
    canvas.setFont("Times-Roman", 7) # Serif for legal text
    canvas.drawString(doc.leftMargin, footer_y, "This document contains proprietary information. Unauthorized text distribution is prohibited.")
    
    # 3. Page Number
    page_num_text = f"Page {doc.page}"
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - doc.rightMargin, footer_y, page_num_text)

    canvas.restoreState()


def draw_cover_page(canvas, doc, period_text: str):
    """
    Dedicated High-End Cover Page.
    """
    canvas.saveState()
    width, height = A4
    
    # 1. Background Accent (Subtle side bar)
    canvas.setFillColor(THEME["primary"])
    canvas.rect(0, 0, 2*cm, height, fill=1, stroke=0)
    
    # 2. Gold Accent Line
    canvas.setFillColor(THEME["accent"])
    canvas.rect(2*cm, 0, 0.2*cm, height, fill=1, stroke=0)
    
    # 3. Main Content Area
    content_x = 4*cm
    
    # Top Branding
    canvas.setFillColor(THEME["primary"])
    canvas.setFont("Times-Bold", 42)
    canvas.drawString(content_x, height - 8*cm, "MONTHLY")
    canvas.drawString(content_x, height - 9.5*cm, "FINANCIAL")
    canvas.drawString(content_x, height - 11*cm, "REPORT")
    
    # Period
    canvas.setFillColor(THEME["accent"])
    canvas.setFont("Helvetica", 18)
    canvas.drawString(content_x, height - 13*cm, period_text.upper())
    
    # Divider
    canvas.setStrokeColor(THEME["muted"])
    canvas.setLineWidth(1)
    canvas.line(content_x, height - 14*cm, width - 2*cm, height - 14*cm)
    
    # "Prepared For" Section
    canvas.setFillColor(THEME["muted"])
    canvas.setFont("Helvetica", 10)
    canvas.drawString(content_x, height - 16*cm, "PREPARED FOR:")
    
    canvas.setFillColor(THEME["text"])
    canvas.setFont("Times-Bold", 14)
    canvas.drawString(content_x, height - 16.7*cm, "EXECUTIVE MANAGEMENT")
    
    # Bottom Date/Confidential
    canvas.setFillColor(THEME["muted"])
    canvas.setFont("Helvetica", 9)
    canvas.drawString(content_x, 3*cm, f"Generated on: {datetime.now().strftime('%d %B %Y')}")
    canvas.drawString(content_x, 2.5*cm, "STRICTLY PRIVATE & CONFIDENTIAL")

    canvas.restoreState()


class FinancialReportDoc(BaseDocTemplate):
    """Executive document template."""
    def __init__(self, filename: str, period_text: str, title_text: str, **kwargs):
        super().__init__(filename, **kwargs)
        self.period_text = period_text
        self.title_text = title_text


# =========================
# REPORT BUILDER (High-End EXECUTIVE)
# =========================

def build_story(
    data: Dict,
    consolidated_pnl: Dict,
    company_summaries: List[Dict],
    project_summaries: List[Dict],
    fonts: Dict[str, str],
    styles,
    max_projects_detail: int,
    max_tx_appendix: int,
) -> List:
    """Build Executive report story."""
    story: List = []
    
    # 1. PAGE BREAK IS AUTOMATIC AFTER COVER PAGE (Page 1)
    # Strategy: 
    #   - Page 1: Cover Template. We add a spacer to ensure it renders "something" on page 1.
    #   - Page 2+: Normal Template (Letterhead).
    
    # Force content on Page 1 so the Cover Template triggers 'onPage'
    story.append(Spacer(1, 1)) 
    story.append(NextPageTemplate("Normal"))
    story.append(PageBreak()) 

    # Page Width (Portrait)
    page_width = A4[0] - 3.0*cm

    # 2. Executive Summary Block
    story.append(Paragraph("EXECUTIVE SUMMARY", styles["SectionTitle"]))
    story.append(Spacer(1, 2*mm))
    
    fs = create_financial_summary(
        consolidated_pnl["income"],
        consolidated_pnl["expense"],
        consolidated_pnl["profit"],
        width=page_width
    )
    story.append(fs)
    story.append(Spacer(1, 6*mm)) 

    # 3. Consolidated P&L (Detailed)
    story.append(Paragraph("CONSOLIDATED STATEMENT OF INCOME", styles["SectionTitle"]))
    story.append(Spacer(1, 2*mm))
    
    t_pnl = create_pnl_table(consolidated_pnl, fonts=fonts, width=page_width)
    story.append(t_pnl)
    story.append(Spacer(1, 6*mm))

    # 4. Visual Analysis (Charts)
    story.append(Paragraph("FINANCIAL VISUALIZATION", styles["SectionTitle"]))
    
    # Charts need height?
    # Ensure they don't break across pages awkwardly
    chart_h = 5*cm
    
    story.append(Paragraph("Profitability by Project (Top Performers)", styles["H2"]))
    d_proj = create_project_profit_chart(project_summaries, width=page_width, height=chart_h)
    story.append(d_proj)
    story.append(Spacer(1, 4*mm))
    
    story.append(Paragraph("Expense Composition", styles["H2"]))
    d_cat = create_expense_category_chart(consolidated_pnl["by_category"], width=page_width, height=chart_h)
    story.append(d_cat)
    
    # story.append(PageBreak())  <-- Removed forced break
    story.append(Spacer(1, 8*mm))

    # 4. Detailed Breakdown
    story.append(Paragraph("DETAILED PERFORMANCE ANALYSIS (By Net Profit)", styles["SectionTitle"]))
    story.append(Spacer(1, 2*mm))
    
    # Explicitly sort by profit descending to ensure "Urutkan dari yang terbesar" is respected
    sorted_details = sorted(project_summaries, key=lambda x: x["profit"], reverse=True)
    detail_count = min(max_projects_detail, len(sorted_details))
    
    for i, proj_summary in enumerate(sorted_details[:detail_count], 1):
        project_name = proj_summary["name"]
        txs = data["by_project"].get(project_name, [])
        proj_pnl = calculate_pnl(txs)
        
        # Keep together block
        block = []
        
        # Header: Name | Profit
        profit = proj_pnl['profit']
        # Executive style: Colors for profit only if negative? Or always Navy?
        # Let's use Navy for Name, and Standard color logic for numbers.
        
        p_color = THEME['text'] if profit >= 0 else THEME['danger'] # Use text color for positive, red for loss
        if profit >= 0: p_color = THEME["primary"] # Actually Navy for profit looks better
        
        header_html = f'<font name="Times-Bold" color="{THEME["primary"].hexval()}">{i}. {project_name}</font>'
        block.append(Paragraph(header_html, styles["H2"]))
        
        # Sub-header stats (Sans-Serif)
        stats = f"<b>Net Profit: {format_currency(profit)}</b>  |  Rev: {format_currency(proj_pnl['income'])}  |  Exp: {format_currency(proj_pnl['expense'])}"
        block.append(Paragraph(stats, styles["Normal"]))

        # Top expenses list (Bulleted)
        if proj_pnl["expense"] > 0 and proj_pnl["expense_transactions"]:
            block.append(Spacer(1, 1*mm))
            block.append(Paragraph("Key Expenses (Highest First):", styles["Label"]))
            # RE-SORT expenses just to be safe
            sorted_expenses = sorted(proj_pnl["expense_transactions"], key=lambda x: _to_int(x.get("jumlah", 0)), reverse=True)
            top_ex = sorted_expenses[:3]
            for tx in top_ex:
                # Indented slightly
                line = f"&nbsp;&nbsp;&bull; {_safe_str(tx.get('keterangan',''))}: {format_currency(_to_int(tx.get('jumlah',0)))}"
                block.append(Paragraph(line, styles["Muted"]))
            
        block.append(Spacer(1, 4*mm))
        block.append(Divider(page_width, thickness=0.25, color=THEME["border"])) # Very thin separator
        block.append(Spacer(1, 4*mm))
        
        story.append(KeepTogether(block))

    # 5. Appendix (Anomalies)
    # story.append(PageBreak()) <-- Removed forced break
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("AUDIT NOTES & ANOMALIES", styles["SectionTitle"]))
    story.append(Spacer(1, 2*mm))
    
    anomalies = []
    for tx in data["transactions"]:
        issues = []
        if not _safe_str(tx.get("nama_projek", "")).strip() or tx.get("nama_projek") == "(Belum Diisi)": issues.append("Missing Project Code")
        if not _safe_str(tx.get("sumber_dana", "")).strip(): issues.append("Missing Source")
        if issues:
            anomalies.append(f"Date: {tx.get('tanggal')} | Amt: {format_currency(_to_int(tx.get('jumlah',0)))} | Ref: {tx.get('keterangan','')} -> {', '.join(issues)}")
    
    if anomalies:
        story.append(Paragraph(f"Identified {len(anomalies)} data integrity issues:", styles["Muted"]))
        story.append(Spacer(1, 2*mm))
        for a in anomalies[:20]:
            story.append(Paragraph(f"• {a}", styles["Muted"]))
    else:
        story.append(Paragraph("No data integrity issues identified.", styles["Muted"]))

    return story

# =========================
# MAIN GENERATOR
# =========================

def generate_pdf_report(
    year: int,
    month: int,
    output_dir: Optional[str] = None,
    max_projects_detail: int = 12,
    max_tx_appendix: int = 200,
) -> str:
    """
    Generate Executive PDF report.
    """
    data = get_monthly_data(year, month)
    # Check data validity here or inside build logic
    if not data["transactions"]:
        # Fallback empty data if needed, but raising error is fine
        # raise ValueError(f"Tidak ada transaksi untuk {data['period']}")
        pass

    consolidated_pnl = calculate_pnl(data["transactions"])

    # Company summaries
    company_summaries = []
    for company in COMPANY_SHEETS:
        company_txs = data["by_company"].get(company, [])
        cpnl = calculate_pnl(company_txs)
        company_summaries.append({
            "name": company,
            "income": cpnl["income"],
            "expense": cpnl["expense"],
            "profit": cpnl["profit"],
        })

    # Project summaries
    project_summaries = []
    for project, txs in data["by_project"].items():
        ppnl = calculate_pnl(txs)
        company = _safe_str(txs[0].get("company_sheet", "")) if txs else ""
        project_summaries.append({
            "name": project,
            "company": company,
            "income": ppnl["income"],
            "expense": ppnl["expense"],
            "profit": ppnl["profit"],
        })
    project_summaries.sort(key=lambda x: x["profit"], reverse=True)

    # Output
    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)

    fname = _safe_filename(f"Laporan_Keuangan_{year}_{month:02d}") + ".pdf"
    output_path = os.path.join(out_dir, fname)

    # Fonts + styles
    fonts = register_fonts()
    styles = create_styles(fonts)

    # Document setup with page templates - A4 PORTRAIT
    title_text = "Laporan Keuangan Bulanan"
    period_text = data["period"]

    doc = FinancialReportDoc(
        output_path,
        period_text=period_text,
        title_text=title_text,
        pagesize=A4,            # Standard Portrait
        leftMargin=1.5*cm,
        rightMargin=1.5*cm,
        topMargin=2.5*cm,       # Top margin
        bottomMargin=2.0*cm,
    )

    # 1. Cover Template (No headers)
    cover_frame = Frame(0, 0, A4[0], A4[1], id="cover", showBoundary=0, leftPadding=0, bottomPadding=0, rightPadding=0, topPadding=0)
    cover_template = PageTemplate(
        id="Cover",
        frames=[cover_frame],
        onPage=lambda c, d: draw_cover_page(c, d, period_text=period_text),
    )

    # 2. Normal Template (Letterhead)
    normal_frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="normal",
        showBoundary=0,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0
    )
    normal_template = PageTemplate(
        id="Normal",
        frames=[normal_frame],
        onPage=lambda c, d: draw_header_footer(c, d, period_text=period_text, title_text=title_text),
    )

    # Add templates (Cover first)
    doc.addPageTemplates([cover_template, normal_template])

    story = build_story(
        data=data,
        consolidated_pnl=consolidated_pnl,
        company_summaries=company_summaries,
        project_summaries=project_summaries,
        fonts=fonts,
        styles=styles,
        max_projects_detail=max_projects_detail,
        max_tx_appendix=max_tx_appendix,
    )

    doc.build(story)

    secure_log("INFO", f"PDF generated: {output_path}")
    return output_path


def _build_context_monthly(year: int, month: int) -> Dict:
    all_txs = _get_all_transactions_v2()
    start_dt, end_dt = _month_start_end(year, month)
    period_txs = _filter_period(all_txs, start_dt, end_dt)

    if not period_txs:
        raise ValueError("Tidak ada data di periode tersebut.")

    prev_year, prev_month = _prev_month(year, month)
    prev_start, prev_end = _month_start_end(prev_year, prev_month)
    prev_txs = _filter_period(all_txs, prev_start, prev_end)

    summary = _summarize_period(period_txs)
    prev_summary = _summarize_period(prev_txs)

    company_period = {c: [] for c in COMPANY_ORDER_V2}
    company_prev = {c: [] for c in COMPANY_ORDER_V2}

    for tx in period_txs:
        comp = _company_from_tx(tx)
        if comp in company_period:
            company_period[comp].append(tx)

    for tx in prev_txs:
        comp = _company_from_tx(tx)
        if comp in company_prev:
            company_prev[comp].append(tx)

    income_by_company = {}
    for comp in COMPANY_ORDER_V2:
        income_by_company[comp] = sum(tx["jumlah"] for tx in company_period[comp] if _is_income(tx))

    total_income = sum(income_by_company.values()) or 1
    income_share = {c: (income_by_company[c] / total_income) * 100 for c in COMPANY_ORDER_V2}

    finished_projects = _finished_projects_by_company(period_txs)

    projects_all = {}
    for tx in all_txs:
        if tx.get("company_sheet") == OFFICE_SHEET_NAME:
            continue
        proj = tx.get("nama_projek", "").strip()
        if not proj:
            continue
        proj_l = proj.lower()
        if proj_l in {"operasional kantor", "saldo umum", "umum", "unknown"}:
            continue
        projects_all.setdefault(proj, []).append(tx)

    company_details = {}
    for comp in COMPANY_ORDER_V2:
        period_list = company_period[comp]
        prev_list = company_prev[comp]
        comp_summary = _summarize_period(period_list)
        comp_prev = _summarize_period(prev_list)

        income_txs = sorted([t for t in period_list if _is_income(t)], key=lambda x: x["jumlah"], reverse=True)
        expense_txs = sorted([t for t in period_list if _is_expense(t) and not _is_salary(t)], key=lambda x: x["jumlah"], reverse=True)
        salary_txs = sorted([t for t in period_list if _is_salary(t)], key=lambda x: x["jumlah"], reverse=True)

        finished_metrics = []
        for proj in finished_projects.get(comp, []):
            metrics = _project_metrics(projects_all.get(proj, []))
            finished_metrics.append({
                "name": strip_company_prefix(proj) or proj,
                "metrics": metrics,
            })

        company_details[comp] = {
            "summary": comp_summary,
            "prev_summary": comp_prev,
            "income_txs": income_txs,
            "expense_txs": expense_txs,
            "salary_txs": salary_txs,
            "finished_projects": finished_metrics,
        }

    return {
        "mode": "monthly",
        "period_label": format_period_label(year, month),
        "generated_on": format_generated_on(),
        "summary": summary,
        "prev_summary": prev_summary,
        "income_share": income_share,
        "finished_projects": finished_projects,
        "company_details": company_details,
    }


def _build_context_range(start_dt: datetime, end_dt: datetime) -> Dict:
    all_txs = _get_all_transactions_v2()
    period_txs = _filter_period(all_txs, start_dt, end_dt)

    if not period_txs:
        raise ValueError("Tidak ada data di periode tersebut.")

    summary = _summarize_period(period_txs)

    company_period = {c: [] for c in COMPANY_ORDER_V2}
    for tx in period_txs:
        comp = _company_from_tx(tx)
        if comp in company_period:
            company_period[comp].append(tx)

    income_by_company = {}
    for comp in COMPANY_ORDER_V2:
        income_by_company[comp] = sum(tx["jumlah"] for tx in company_period[comp] if _is_income(tx))

    total_income = sum(income_by_company.values()) or 1
    income_share = {c: (income_by_company[c] / total_income) * 100 for c in COMPANY_ORDER_V2}

    finished_projects = _finished_projects_by_company(period_txs)

    return {
        "mode": "range",
        "generated_on": format_generated_on(),
        "summary": summary,
        "income_share": income_share,
        "finished_projects": finished_projects,
        "start_dt": start_dt,
        "end_dt": end_dt,
    }


def _y_from_top(y_top: float, page_h: float) -> float:
    return page_h - y_top


def _draw_header_monthly(c: canvas.Canvas, ctx: Dict, page_w: float, page_h: float, logo_path: Optional[str] = None):
    header_h = 190
    left_w = 427
    c.setFillColor(THEME_V2["teal"])
    c.rect(0, page_h - header_h, left_w, header_h, fill=1, stroke=0)

    if logo_path and os.path.exists(logo_path):
        c.drawImage(logo_path, 30, page_h - 70, width=120, height=40, mask="auto")

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(130, page_h - 25, f"Generated on {ctx['generated_on']}")

    c.setFont("Helvetica-Bold", 24)
    c.drawString(130, page_h - 60, "Financial")
    c.drawString(130, page_h - 90, "Report")

    c.setFillColor(THEME_V2["teal"])
    c.setFont("Helvetica-Bold", 28)
    month_part, year_part = ctx["period_label"].split()
    c.drawString(left_w + 15, page_h - 60, month_part)
    c.drawString(left_w + 15, page_h - 95, year_part)


def _draw_header_range(c: canvas.Canvas, ctx: Dict, page_w: float, page_h: float, logo_path: Optional[str] = None):
    header_h = 190
    left_w = 427
    c.setFillColor(THEME_V2["teal"])
    c.rect(0, page_h - header_h, left_w, header_h, fill=1, stroke=0)

    if logo_path and os.path.exists(logo_path):
        c.drawImage(logo_path, 30, page_h - 70, width=120, height=40, mask="auto")

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(130, page_h - 25, f"Generated on {ctx['generated_on']}")

    c.setFont("Helvetica-Bold", 24)
    c.drawString(130, page_h - 60, "Financial")
    c.drawString(130, page_h - 90, "Report")

    c.setFillColor(THEME_V2["teal"])
    c.setFont("Helvetica-Bold", 18)
    c.drawString(left_w + 15, page_h - 55, "Periodical Audit")
    c.setFont("Helvetica", 9)
    c.drawString(left_w + 15, page_h - 75, "Dalam rentang waktu")

    c.setFont("Helvetica", 9)
    start_text = ctx["start_dt"].strftime("%d-%m-%y")
    end_text = ctx["end_dt"].strftime("%d-%m-%y")
    c.drawString(left_w + 15, page_h - 95, f"{start_text} (00:00)")
    c.drawString(left_w + 15, page_h - 110, "hingga")
    c.drawString(left_w + 15, page_h - 125, f"{end_text} (00:00)")


def _draw_kpi_block(c: canvas.Canvas, x: float, y_top: float, label: str, amount: int, color, subnote: Optional[str] = None):
    c.setFillColor(THEME_V2["text"])
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(x, y_top, label)

    c.setFont("Helvetica", 8)
    c.drawString(x, y_top - 16, "Rp")

    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x + 18, y_top - 20, format_number(amount))

    if subnote:
        c.setFillColor(color)
        c.setFont("Helvetica", 8)
        c.drawString(x, y_top - 38, subnote)

    c.setStrokeColor(THEME_V2["black"])
    c.setLineWidth(2.5)
    c.line(x, y_top - 46, x + 210, y_top - 46)


def _draw_comparison_column(c: canvas.Canvas, x: float, y_top: float, curr: int, prev: int, label: str):
    c.setFillColor(THEME_V2["text"])
    c.setFont("Helvetica", 8)
    c.drawString(x, y_top, "Bulan lalu")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y_top - 16, format_number(prev))
    c.setFont("Helvetica", 8)
    c.drawString(x, y_top - 32, _insight_text(label, curr, prev))


def _draw_finished_projects_section(c: canvas.Canvas, ctx: Dict, page_w: float, page_h: float, title: str, note: str):
    c.setFillColor(THEME_V2["teal"])
    c.rect(18, page_h - 535, 26, 18, fill=1, stroke=0)

    c.setFillColor(THEME_V2["text"])
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, page_h - 520, title)
    c.setFont("Helvetica", 8)
    c.drawString(260, page_h - 520, note)

    column_x = [30, 160, 290, 420]
    max_items = 6
    for idx, comp in enumerate(COMPANY_ORDER_V2):
        x = column_x[idx]
        c.setFillColor(THEME_V2["text"])
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(x, page_h - 560, comp)
        c.setFillColor(THEME_V2["teal"])
        c.setFont("Helvetica-Bold", 20)
        count = len(ctx["finished_projects"].get(comp, []))
        c.drawString(x, page_h - 585, str(count))

        c.setFillColor(THEME_V2["text"])
        c.setFont("Helvetica", 8)
        projects = ctx["finished_projects"].get(comp, [])
        display = [strip_company_prefix(p) or p for p in projects]
        for i, name in enumerate(display[:max_items]):
            c.drawString(x, page_h - 605 - (i * 12), f"• {name}")
        if len(display) > max_items:
            c.drawString(x, page_h - 605 - (max_items * 12), f"+{len(display) - max_items} lainnya")

    # Income share chart
    chart_x = 460
    chart_y = page_h - 610
    c.setFillColor(THEME_V2["text"])
    c.setFont("Helvetica-Bold", 9)
    c.drawString(chart_x, page_h - 560, "Grafik Pemasukkan")
    bar_max = 100
    for i, comp in enumerate(COMPANY_ORDER_V2):
        pct = ctx["income_share"].get(comp, 0)
        c.setFillColor(COMPANY_THEME_V2.get(comp, THEME_V2["teal"]))
        c.rect(chart_x, chart_y - (i * 18), bar_max * (pct / 100), 8, fill=1, stroke=0)
        c.setFillColor(THEME_V2["text"])
        c.setFont("Helvetica", 7)
        c.drawString(chart_x + bar_max + 5, chart_y - (i * 18) + 1, f"{pct:.0f}%")


def draw_cover_monthly(c: canvas.Canvas, ctx: Dict, logo_path: Optional[str] = None):
    page_w, page_h = A4
    _draw_header_monthly(c, ctx, page_w, page_h, logo_path=logo_path)

    summary = ctx["summary"]
    _draw_kpi_block(
        c, 30, page_h - 230, "OMSET TOTAL", summary["income_total"], THEME_V2["text"]
    )
    _draw_kpi_block(
        c, 30, page_h - 310, "PENGELUARAN TOTAL", summary["expense_total"], THEME_V2["pink"],
        subnote=f"(Pengeluaran Kantor Rp {format_number(summary['office_expense'])})"
    )
    _draw_kpi_block(
        c, 30, page_h - 390, "PROFIT", summary["profit"], THEME_V2["teal"]
    )

    c.setStrokeColor(THEME_V2["black"])
    c.setLineWidth(3)
    c.line(320, page_h - 220, 320, page_h - 430)

    prev = ctx["prev_summary"]
    _draw_comparison_column(c, 340, page_h - 240, summary["income_total"], prev["income_total"], "income")
    _draw_comparison_column(c, 340, page_h - 300, summary["expense_total"], prev["expense_total"], "expense")
    _draw_comparison_column(c, 340, page_h - 360, summary["profit"], prev["profit"], "profit")

    _draw_finished_projects_section(
        c,
        ctx,
        page_w,
        page_h,
        "Project yang Selesai Bulan ini",
        "Adalah Project, yang telah tuntas pada bulan ini. Untuk mulainya tidak harus bulan ini.",
    )


def draw_cover_periodical(c: canvas.Canvas, ctx: Dict, logo_path: Optional[str] = None):
    page_w, page_h = A4
    _draw_header_range(c, ctx, page_w, page_h, logo_path=logo_path)

    summary = ctx["summary"]
    _draw_kpi_block(
        c, 30, page_h - 230, "OMSET TOTAL", summary["income_total"], THEME_V2["text"]
    )
    _draw_kpi_block(
        c, 30, page_h - 310, "PENGELUARAN TOTAL", summary["expense_total"], THEME_V2["pink"],
        subnote=f"(Pengeluaran Kantor Rp {format_number(summary['office_expense'])})"
    )
    _draw_kpi_block(
        c, 30, page_h - 390, "PROFIT", summary["profit"], THEME_V2["teal"]
    )

    c.setStrokeColor(THEME_V2["black"])
    c.setLineWidth(3)
    c.line(320, page_h - 220, 320, page_h - 430)

    _draw_finished_projects_section(
        c,
        ctx,
        page_w,
        page_h,
        "Project Selesai",
        "Adalah Project, yang telah tuntas pada periode ini.",
    )


def draw_company_page(c: canvas.Canvas, ctx: Dict, company: str):
    page_w, page_h = (A4[0], 1621)
    color = COMPANY_THEME_V2.get(company, THEME_V2["teal"])
    c.setFillColor(color)
    c.rect(0, page_h - 130, page_w, 130, fill=1, stroke=0)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(30, page_h - 60, company)
    c.setFont("Helvetica-Bold", 18)
    month_part, year_part = ctx["period_label"].split()
    c.drawRightString(page_w - 30, page_h - 60, month_part)
    c.drawRightString(page_w - 30, page_h - 85, year_part)

    details = ctx["company_details"][company]
    summary = details["summary"]
    prev = details["prev_summary"]

    _draw_kpi_block(c, 30, page_h - 180, "OMSET TOTAL", summary["income_total"], THEME_V2["text"])
    _draw_kpi_block(c, 30, page_h - 260, "PENGELUARAN TOTAL", summary["expense_total"], THEME_V2["pink"])
    _draw_kpi_block(c, 30, page_h - 340, "PROFIT", summary["profit"], THEME_V2["teal"])

    c.setStrokeColor(THEME_V2["black"])
    c.setLineWidth(2)
    c.line(260, page_h - 180, 260, page_h - 340)

    _draw_comparison_column(c, 280, page_h - 200, summary["income_total"], prev["income_total"], "income")
    _draw_comparison_column(c, 280, page_h - 260, summary["expense_total"], prev["expense_total"], "expense")
    _draw_comparison_column(c, 280, page_h - 320, summary["profit"], prev["profit"], "profit")

    # Lists
    list_y = page_h - 420
    c.setFillColor(THEME_V2["text"])
    c.setFont("Helvetica-Bold", 11)
    c.drawString(30, list_y, "List Pemasukan")
    c.drawString(210, list_y, "List Pengeluaran")
    c.drawString(390, list_y, "List Gaji")

    c.setFont("Helvetica", 8)
    for i, tx in enumerate(details["income_txs"][:6]):
        c.drawString(30, list_y - 15 - (i * 12), f"{i+1}. {tx['keterangan'][:22]}  Rp {format_number(tx['jumlah'])}")
    for i, tx in enumerate(details["expense_txs"][:6]):
        c.drawString(210, list_y - 15 - (i * 12), f"{i+1}. {tx['keterangan'][:22]}  Rp {format_number(tx['jumlah'])}")
    for i, tx in enumerate(details["salary_txs"][:6]):
        c.drawString(390, list_y - 15 - (i * 12), f"{i+1}. {tx['keterangan'][:22]}  Rp {format_number(tx['jumlah'])}")

    # Finished projects
    section_y = list_y - 120
    c.setStrokeColor(THEME_V2["black"])
    c.setLineWidth(3)
    c.line(30, section_y, page_w - 30, section_y)

    c.setFillColor(THEME_V2["text"])
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30, section_y - 25, "Finished Projects")

    row_y = section_y - 45
    c.setFont("Helvetica", 8)
    for idx, item in enumerate(details["finished_projects"][:8], start=1):
        metrics = item["metrics"]
        c.drawString(30, row_y - (idx * 14), f"{idx}. {item['name'][:40]}")
        c.drawRightString(page_w - 30, row_y - (idx * 14), f"Profit {format_number(metrics['profit'])}")

    if len(details["finished_projects"]) > 8:
        c.drawString(30, row_y - (9 * 14), f"+{len(details['finished_projects']) - 8} lainnya")


def generate_pdf_report_v2_monthly(year: int, month: int, output_dir: Optional[str] = None) -> str:
    ctx = _build_context_monthly(year, month)
    period_label = ctx["period_label"]
    fname = _safe_filename(f"Laporan_Keuangan_{period_label}") + ".pdf"
    output_path = os.path.join(output_dir or tempfile.gettempdir(), fname)

    logo_path = os.getenv("HOLLAWALL_LOGO_PATH")
    c = canvas.Canvas(output_path, pagesize=A4)
    draw_cover_monthly(c, ctx, logo_path=logo_path)
    c.showPage()

    c.setPageSize((A4[0], 1621))
    for comp in COMPANY_ORDER_V2:
        draw_company_page(c, ctx, comp)
        c.showPage()

    c.save()
    secure_log("INFO", f"PDF generated: {output_path}")
    return output_path


def generate_pdf_report_v2_range(start_dt: datetime, end_dt: datetime, output_dir: Optional[str] = None) -> str:
    ctx = _build_context_range(start_dt, end_dt)
    fname = _safe_filename(f"Laporan_Keuangan_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}") + ".pdf"
    output_path = os.path.join(output_dir or tempfile.gettempdir(), fname)

    logo_path = os.getenv("HOLLAWALL_LOGO_PATH")
    c = canvas.Canvas(output_path, pagesize=A4)
    draw_cover_periodical(c, ctx, logo_path=logo_path)
    c.save()
    secure_log("INFO", f"PDF generated: {output_path}")
    return output_path


def _parse_range_input(period_input: str) -> Optional[Tuple[datetime, datetime]]:
    matches = re.findall(r"\d{4}-\d{2}-\d{2}", period_input or "")
    if len(matches) >= 2:
        start = datetime.strptime(matches[0], "%Y-%m-%d")
        end = datetime.strptime(matches[1], "%Y-%m-%d")
        if end < start:
            start, end = end, start
        return start, end
    return None


def generate_pdf_from_input(
    month_input: str,
    output_dir: Optional[str] = None,
    max_projects_detail: int = 12,
    max_tx_appendix: int = 200,
) -> str:
    range_input = _parse_range_input(month_input)
    if range_input:
        start_dt, end_dt = range_input
        return generate_pdf_report_v2_range(start_dt, end_dt, output_dir=output_dir)

    year, month = parse_month_input(month_input)
    return generate_pdf_report_v2_monthly(
        year=year,
        month=month,
        output_dir=output_dir,
    )


# =========================
# TESTING
# =========================

if __name__ == "__main__":
    print("=" * 60)
    print("Premium PDF Report Generator Test (ReportLab)")
    print("=" * 60)

    # 1) month parsing
    tests = ["2026-01", "januari 2026", "jan 2026", "01/2026", "02-2026"]
    for t in tests:
        try:
            y, m = parse_month_input(t)
            print(f"[OK] '{t}' -> year={y}, month={m}")
        except Exception as e:
            print(f"[ERR] '{t}' -> {e}")

    # 2) data fetch + PDF generate (requires your sheets_helper configured)
    try:
        year, month = 2026, 1
        data = get_monthly_data(year, month)
        print(f"\nTransactions: {len(data['transactions'])} | Period: {data['period']}")

        out = generate_pdf_report(year, month)
        size_kb = os.path.getsize(out) / 1024
        print(f"PDF: {out}")
        print(f"Size: {size_kb:.1f} KB")
    except Exception as e:
        print("\nPDF generation failed:")
        print(e)
