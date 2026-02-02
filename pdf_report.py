# -*- coding: utf-8 -*-
"""
pdf_report_redesigned.py - Finance Bot PDF Export (REDESIGNED - Premium Professional v4)

🎨 REDESIGN GOALS:
- Bigger, readable fonts throughout (min 10pt for body text)
- Generous, consistent spacing and padding
- Softer, multi-layer shadows for depth
- Subtle borders and dividers
- Strong typography hierarchy
- Professional, modern aesthetic
- Clean layout with proper breathing room

📝 KEY IMPROVEMENTS FROM v3:
1. Font Sizes:
   - Titles: 14-16pt (was 11-14pt)
   - Body: 10-11pt (was 9-9.5pt)
   - Numbers: 24-28pt for KPIs (was 20-24pt)
   - Labels: 10pt (was 9pt)

2. Spacing:
   - Card padding: 20px (was 12-16px)
   - Margins: 40px (was 36px)
   - Line height: 16-18px (was 12-14px)
   - Card gaps: 20px (was 12-14px)

3. Shadows:
   - 3-layer system for depth
   - Softer alpha values (0.03-0.06)
   - Better offset positioning

4. Colors & Borders:
   - Lighter border colors (#E5E7EB vs #E2E8F0)
   - More contrast in text hierarchy
   - Better accent color usage

5. Cards:
   - Increased border radius (18px vs 16px)
   - Top accent bars (4px height)
   - Better internal spacing
"""

from __future__ import annotations

import os
import re
import math
import calendar
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont

# Your existing modules
from sheets_helper import get_all_data
from security import secure_log
from config.wallets import extract_company_prefix, strip_company_prefix


# =============================================================================
# Errors (user-friendly for bot feedback)
# =============================================================================

class PDFReportError(Exception):
    """Base class for PDF export errors."""
    pass


class PDFInputError(PDFReportError):
    """Raised when user input format is invalid."""
    pass


class PDFNoDataError(PDFReportError):
    """Raised when requested period has no transactions."""
    def __init__(self, period_label: str):
        super().__init__(f"Tidak ada data transaksi untuk periode: {period_label}")
        self.period_label = period_label


# =============================================================================
# Theme (REDESIGNED - More professional palette)
# =============================================================================

THEME = {
    # Backgrounds
    "bg": colors.HexColor("#F9FAFB"),         # Gray-50 - lighter, airier
    "card": colors.white,
    "card_alt": colors.HexColor("#FAFBFC"),   
    
    # Borders & Dividers - lighter for subtlety
    "border": colors.HexColor("#E5E7EB"),     # Gray-200 - softer than before
    "border_light": colors.HexColor("#F3F4F6"), # Gray-100 - ultra subtle
    "divider": colors.HexColor("#E5E7EB"),
    
    # Shadows
    "shadow": colors.HexColor("#111827"),     # Gray-900 - deep shadow
    "track": colors.HexColor("#F3F4F6"),      # Gray-100 - subtle track
    
    # Text hierarchy - stronger contrast
    "text": colors.HexColor("#111827"),       # Gray-900 - darker for readability
    "text_secondary": colors.HexColor("#374151"), # Gray-700
    "muted": colors.HexColor("#6B7280"),      # Gray-500 - readable muted
    "muted2": colors.HexColor("#9CA3AF"),     # Gray-400 - lighter muted
    
    # Primary accent
    "accent": colors.HexColor("#0EA5E9"),     # Sky-500
    "accent_dark": colors.HexColor("#0284C7"), # Sky-600
    "accent_light": colors.HexColor("#7DD3FC"), # Sky-300
    
    # Status colors
    "success": colors.HexColor("#10B981"),    # Emerald-500
    "success_light": colors.HexColor("#D1FAE5"),
    "warning": colors.HexColor("#F59E0B"),    # Amber-500
    "warning_light": colors.HexColor("#FEF3C7"),
    "danger": colors.HexColor("#EF4444"),     # Red-500
    "danger_light": colors.HexColor("#FEE2E2"),
    "white": colors.white,
    
    # Legacy aliases
    "teal": colors.HexColor("#0EA5E9"),
    "teal2": colors.HexColor("#0284C7"),
    "pink": colors.HexColor("#EF4444"),
    "green": colors.HexColor("#10B981"),
}

COMPANY_KEYS = ["Hollawall", "Hojja", "Texturin Surabaya", "Texturin Bali"]

COMPANY_DISPLAY = {
    "Hollawall": "Hollawall Mural",
    "Hojja": "Hojja",
    "Texturin Surabaya": "Texturin Surabaya",
    "Texturin Bali": "Texturin Bali",
}

COMPANY_DISPLAY_COVER = {
    "Hollawall": "Hollawall",
    "Hojja": "Hojja",
    "Texturin Surabaya": "Texturin",
    "Texturin Bali": "Texturin Bali",
}

COMPANY_COLOR = {
    "Hollawall": colors.HexColor("#0891B2"),
    "Hojja": colors.HexColor("#059669"),
    "Texturin Surabaya": colors.HexColor("#B45309"),
    "Texturin Bali": colors.HexColor("#D97706"),
}

OFFICE_SHEET_NAME = "Operasional Kantor"

PELUNASAN_KEYWORDS = ["pelunasan", "lunas", "final payment", "penyelesaian", "closing"]
PROJECT_EXCLUDE_NAMES = {"operasional", "operasional kantor", "saldo umum", "umum", "unknown", "(belum diisi)", "belum diisi"}


# =============================================================================
# Fonts (Optional)
# =============================================================================

def register_fonts() -> Dict[str, str]:
    """
    Optional fonts in ./assets/fonts/ (recommended):
      - Inter-Regular.ttf
      - Inter-SemiBold.ttf
      - Inter-Bold.ttf

    Returns:
        dict with keys: regular, semibold, bold, italic
    """
    base_dir = os.path.dirname(__file__)
    font_dir = os.path.join(base_dir, "assets", "fonts")

    candidates = {
        "regular": ("Inter", os.path.join(font_dir, "Inter-Regular.ttf")),
        "semibold": ("Inter-SemiBold", os.path.join(font_dir, "Inter-SemiBold.ttf")),
        "bold": ("Inter-Bold", os.path.join(font_dir, "Inter-Bold.ttf")),
        "italic": ("Inter-Italic", os.path.join(font_dir, "Inter-Italic.ttf")),
    }

    fonts = {
        "regular": "Helvetica",
        "semibold": "Helvetica-Bold",
        "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique",
    }

    ok_any = False
    for key, (name, path) in candidates.items():
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                fonts[key] = name
                ok_any = True
            except Exception:
                pass

    if ok_any and fonts.get("italic") == "Inter-Italic" and not os.path.exists(candidates["italic"][1]):
        fonts["italic"] = "Helvetica-Oblique"

    return fonts


# =============================================================================
# Safe helpers (same as before)
# =============================================================================

def _safe_str(v: object, default: str = "") -> str:
    if v is None:
        return default
    return str(v)

def _to_int(v: object, default: int = 0) -> int:
    if v is None or isinstance(v, bool):
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

def format_number(amount: int) -> str:
    return f"{amount:,.0f}".replace(",", ".")

def format_currency(amount: int) -> str:
    return f"Rp {format_number(amount)}"

def _safe_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", (name or "").strip())
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "report"

def _month_start_end(year: int, month: int) -> Tuple[datetime, datetime]:
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1, 0, 0, 0)
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end

def _prev_month(year: int, month: int) -> Tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1

def format_period_label(year: int, month: int) -> str:
    return f"{calendar.month_abbr[month].upper()} {str(year)[-2:]}"

def format_generated_on(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now()).strftime("%d %b %y")

def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


# =============================================================================
# Input parsing (same as before - keeping for compatibility)
# =============================================================================

MIN_YEAR = 2020
MAX_YEAR = 2100

def _normalize_user_input(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"^\s*/exportpdf\b", "", s, flags=re.IGNORECASE).strip()
    return s

def parse_month_input(month_input: str) -> Tuple[int, int]:
    month_input = (month_input or "").strip().lower()
    if not month_input:
        raise PDFInputError("Input periode kosong. Contoh: 2026-01 atau Januari 2026")

    year = None
    month = None

    if "-" in month_input or "/" in month_input:
        sep = "-" if "-" in month_input else "/"
        parts = [p.strip() for p in month_input.split(sep) if p.strip()]
        if len(parts) == 2:
            try:
                p0 = int(parts[0]); p1 = int(parts[1])
                if p0 >= 1000:
                    year, month = p0, p1
                else:
                    month, year = p0, p1
            except ValueError:
                raise PDFInputError(f"Format bulan tidak valid: '{month_input}'. Contoh: 2026-01 atau 01-2026")

    if year is None or month is None:
        month_map = {
            "januari": 1, "jan": 1,
            "februari": 2, "feb": 2,
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
        for key, mnum in month_map.items():
            if re.search(rf"\b{re.escape(key)}\b", month_input):
                ym = re.search(r"(\d{4})", month_input)
                if not ym:
                    raise PDFInputError(f"Tahun tidak ditemukan: '{month_input}'. Contoh: Januari 2026")
                year = int(ym.group(1))
                month = mnum
                break

    if year is None or month is None:
        raise PDFInputError(
            f"Format periode tidak dikenali: '{month_input}'.\n"
            "Contoh:\n"
            "• /exportpdf 2026-01\n"
            "• /exportpdf Januari 2026\n"
            "• /exportpdf 12-01-2026 - 20-01-2026"
        )

    if month < 1 or month > 12:
        raise PDFInputError(f"Bulan tidak valid: {month}. Harus 1-12.")
    if year < MIN_YEAR or year > MAX_YEAR:
        raise PDFInputError(f"Tahun tidak valid: {year}. Harus {MIN_YEAR}-{MAX_YEAR}.")

    return year, month

def _parse_any_date_token(token: str) -> Optional[datetime]:
    token = (token or "").strip()
    if not token:
        return None
    fmts = [
        "%Y-%m-%d", "%Y/%m/%d",
        "%d-%m-%Y", "%d/%m/%Y",
        "%d-%m-%y", "%d/%m/%y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(token, fmt)
        except ValueError:
            continue
    return None

def parse_range_input(text: str) -> Optional[Tuple[datetime, datetime]]:
    s = (text or "").strip()
    tokens = re.findall(r"(?:\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{2,4})", s)
    if len(tokens) < 2:
        return None

    dt1 = _parse_any_date_token(tokens[0])
    dt2 = _parse_any_date_token(tokens[1])
    if not dt1 or not dt2:
        raise PDFInputError(
            "Format rentang tanggal tidak valid.\n"
            "Contoh: /exportpdf 12-01-2026 - 20-01-2026"
        )

    start = datetime(dt1.year, dt1.month, dt1.day, 0, 0, 0)
    end = datetime(dt2.year, dt2.month, dt2.day, 23, 59, 59)

    if end < start:
        start, end = end, start

    if start.year < MIN_YEAR or end.year > MAX_YEAR:
        raise PDFInputError(f"Tahun harus dalam range {MIN_YEAR}-{MAX_YEAR}.")

    return start, end


# =============================================================================
# Data normalization + business rules (KEEPING SAME AS ORIGINAL)
# =============================================================================
# [KEEPING ALL DATA PROCESSING FUNCTIONS FROM ORIGINAL - lines 387-814]
# These are working fine, no need to change:
# - _get_all_data_safe()
# - _parse_date_field()
# - _normalize_tx()
# - _get_all_transactions()
# - _filter_period()
# - _is_income(), _is_expense(), _is_salary()
# - _strip_project_markers(), _has_finish_marker()
# - _project_key(), _project_display_name()
# - _company_from_tx()
# - _summarize_period(), _summarize_company()
# - _pct_change(), _delta_pill()
# - _finished_projects_by_company()
# - _project_metrics()
# - All the data building functions

def _get_all_data_safe() -> List[Dict]:
    try:
        return get_all_data(days=None)  # type: ignore
    except TypeError:
        return get_all_data()  # type: ignore

def _parse_date_field(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d-%m-%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def _normalize_tx(tx: Dict) -> Optional[Dict]:
    dt = _parse_date_field(_safe_str(tx.get("tanggal", "")).strip())
    if not dt:
        return None
    return {
        "tanggal": _safe_str(tx.get("tanggal", "")).strip(),
        "dt": dt,
        "keterangan": _safe_str(tx.get("keterangan", "")).strip(),
        "jumlah": _to_int(tx.get("jumlah", 0)),
        "tipe": _safe_str(tx.get("tipe", "Pengeluaran")).strip(),
        "kategori": _safe_str(tx.get("kategori", "Lain-lain")).strip() or "Lain-lain",
        "company_sheet": _safe_str(tx.get("company_sheet", "Unknown")).strip(),
        "nama_projek": _safe_str(tx.get("nama_projek", "")).strip(),
    }

def _get_all_transactions() -> List[Dict]:
    raw = _get_all_data_safe()
    out: List[Dict] = []
    for tx in raw:
        ntx = _normalize_tx(tx)
        if ntx:
            out.append(ntx)
    return out

def _filter_period(transactions: Iterable[Dict], start_dt: datetime, end_dt: datetime) -> List[Dict]:
    out: List[Dict] = []
    for tx in transactions:
        dt = tx.get("dt")
        if not isinstance(dt, datetime):
            continue
        if start_dt <= dt <= end_dt:
            out.append(tx)
    return out

def _is_income(tx: Dict) -> bool:
    return "pemasukan" in (tx.get("tipe", "") or "").lower()

def _is_expense(tx: Dict) -> bool:
    return not _is_income(tx)

def _is_salary(tx: Dict) -> bool:
    cat = (tx.get("kategori") or "").lower()
    desc = (tx.get("keterangan") or "").lower()
    return "gaji" in cat or "gaji" in desc

def _strip_project_markers(name: str) -> str:
    if not name:
        return ""
    clean = re.sub(r"\s*\((start|finish)\)\s*$", "", name.strip(), flags=re.IGNORECASE)
    return clean.strip()

def _has_finish_marker(name: str) -> bool:
    return "(finish)" in (name or "").lower()

def _project_key(name: str) -> str:
    return _strip_project_markers(name)

def _project_display_name(name: str) -> str:
    base = _strip_project_markers(name)
    stripped = strip_company_prefix(base) or base
    return stripped.strip()

def _company_from_tx(tx: Dict) -> Optional[str]:
    dompet = tx.get("company_sheet")
    if dompet == OFFICE_SHEET_NAME:
        return None

    if dompet == "TX SBY(216)":
        return "Texturin Surabaya"
    if dompet == "TX BALI(087)":
        return "Texturin Bali"

    if dompet == "CV HB (101)":
        project_name = tx.get("nama_projek", "") or ""
        prefix = extract_company_prefix(project_name)
        if prefix == "HOJJA":
            return "Hojja"
        if prefix == "HOLLA":
            return "Hollawall"
        base = _strip_project_markers(project_name).lower()
        if base in PROJECT_EXCLUDE_NAMES:
            return None
        return "Hollawall"

    return None

def _summarize_period(period_txs: List[Dict]) -> Dict:
    income_total = 0
    expense_non_office = 0
    office_expense = 0

    for tx in period_txs:
        amt = int(tx.get("jumlah", 0) or 0)
        if tx.get("company_sheet") == OFFICE_SHEET_NAME:
            if _is_expense(tx):
                office_expense += amt
            continue

        if _is_income(tx):
            income_total += amt
        else:
            expense_non_office += amt

    expense_total = expense_non_office + office_expense
    profit = income_total - expense_total

    return {
        "income_total": income_total,
        "expense_total": expense_total,
        "office_expense": office_expense,
        "profit": profit,
        "expense_non_office": expense_non_office,
    }

def _summarize_company(company_txs: List[Dict]) -> Dict:
    income = sum(int(t.get("jumlah", 0) or 0) for t in company_txs if _is_income(t))
    expense = sum(int(t.get("jumlah", 0) or 0) for t in company_txs if _is_expense(t))
    return {"income_total": income, "expense_total": expense, "profit": income - expense}

def _pct_change(curr: int, prev: int) -> Optional[float]:
    if prev == 0:
        if curr == 0:
            return 0.0
        return None
    return ((curr - prev) / prev) * 100.0

def _delta_pill(label: str, curr: int, prev: int) -> Tuple[str, colors.Color]:
    pct = _pct_change(curr, prev)
    if pct is None:
        return ("New", THEME["teal"])
    if abs(pct) < 0.5:
        return ("0%", THEME["muted"])
    sign = "+" if pct > 0 else ""
    txt = f"{sign}{pct:.0f}%"
    if label == "expense":
        return (txt, THEME["success"] if pct < 0 else THEME["danger"])
    return (txt, THEME["success"] if pct > 0 else THEME["danger"])

def _finished_projects_by_company(period_txs: List[Dict]) -> Dict[str, List[str]]:
    finished = {c: set() for c in COMPANY_KEYS}

    for tx in period_txs:
        comp = _company_from_tx(tx)
        if comp not in finished:
            continue

        proj_raw = (tx.get("nama_projek") or "").strip()
        if not proj_raw:
            continue

        proj_key = _project_key(proj_raw)
        if not proj_key:
            continue
        if proj_key.lower() in PROJECT_EXCLUDE_NAMES:
            continue

        desc = (tx.get("keterangan") or "").lower()

        if _has_finish_marker(proj_raw):
            finished[comp].add(proj_key)
            continue

        if _is_income(tx) and any(k in desc for k in PELUNASAN_KEYWORDS):
            finished[comp].add(proj_key)

    return {k: sorted(list(v)) for k, v in finished.items()}

def _project_metrics(project_txs: List[Dict]) -> Dict:
    dp = dp2 = pelunasan = 0
    total_income = 0
    total_expense = 0
    total_salary = 0

    for tx in project_txs:
        amt = int(tx.get("jumlah", 0) or 0)
        desc = (tx.get("keterangan") or "").lower()

        if _is_income(tx):
            total_income += amt
            if "dp" in desc and "2" in desc:
                dp2 += amt
            elif "dp" in desc:
                dp += amt
            elif any(k in desc for k in PELUNASAN_KEYWORDS):
                pelunasan += amt
        else:
            total_expense += amt
            if _is_salary(tx):
                total_salary += amt

    profit = total_income - total_expense
    margin_pct = int((profit / total_income * 100)) if total_income > 0 else 0

    return {
        "dp": dp,
        "dp2": dp2,
        "pelunasan": pelunasan,
        "total_income": total_income,
        "total_expense": total_expense,
        "total_salary": total_salary,
        "profit": profit,
        "margin_pct": margin_pct,
    }

# [KEEPING ALL DATA CONTEXT BUILDING FUNCTIONS - They work fine]
# Will add them here for completeness...

def _build_context_monthly(year: int, month: int) -> Dict:
    """Build complete context for monthly report (same as original)."""
    start_dt, end_dt = _month_start_end(year, month)
    period_label = format_period_label(year, month)
    
    all_txs = _get_all_transactions()
    period_txs = _filter_period(all_txs, start_dt, end_dt)
    
    if not period_txs:
        raise PDFNoDataError(period_label)
    
    summary = _summarize_period(period_txs)
    
    prev_year, prev_month = _prev_month(year, month)
    prev_start, prev_end = _month_start_end(prev_year, prev_month)
    prev_txs = _filter_period(all_txs, prev_start, prev_end)
    prev_summary = _summarize_period(prev_txs)
    
    company_txs_map = {comp: [] for comp in COMPANY_KEYS}
    for tx in period_txs:
        comp = _company_from_tx(tx)
        if comp and comp in company_txs_map:
            company_txs_map[comp].append(tx)
    
    income_by_company = {}
    for comp in COMPANY_KEYS:
        comp_sum = _summarize_company(company_txs_map[comp])
        income_by_company[comp] = comp_sum["income_total"]
    
    total_income = sum(income_by_company.values())
    income_share = {}
    for comp in COMPANY_KEYS:
        if total_income > 0:
            income_share[comp] = (income_by_company[comp] / total_income) * 100
        else:
            income_share[comp] = 0.0
    
    finished_projects = _finished_projects_by_company(period_txs)
    
    company_details = {}
    for comp in COMPANY_KEYS:
        comp_txs = company_txs_map[comp]
        comp_summary = _summarize_company(comp_txs)
        
        prev_comp_txs = [t for t in prev_txs if _company_from_tx(t) == comp]
        prev_comp_summary = _summarize_company(prev_comp_txs)
        
        income_txs = sorted([t for t in comp_txs if _is_income(t)], 
                           key=lambda x: int(x.get("jumlah", 0) or 0), reverse=True)
        expense_txs_all = [t for t in comp_txs if _is_expense(t) and not _is_salary(t)]
        expense_txs = sorted(expense_txs_all, key=lambda x: int(x.get("jumlah", 0) or 0), reverse=True)
        
        salary_txs = sorted([t for t in comp_txs if _is_salary(t)], 
                           key=lambda x: int(x.get("jumlah", 0) or 0), reverse=True)
        
        finished_proj_names = finished_projects.get(comp, [])
        finished_cards = []
        
        for proj_name in finished_proj_names:
            proj_txs = [t for t in comp_txs if _project_key(t.get("nama_projek", "")) == proj_name]
            if not proj_txs:
                continue
            
            metrics = _project_metrics(proj_txs)
            
            start_dates = [t["dt"] for t in proj_txs if isinstance(t.get("dt"), datetime)]
            finish_dates = [t["dt"] for t in proj_txs if isinstance(t.get("dt"), datetime)]
            
            timeline = {
                "start": min(start_dates) if start_dates else None,
                "finish": max(finish_dates) if finish_dates else None,
            }
            
            proj_expenses = [t for t in proj_txs if _is_expense(t) and not _is_salary(t)]
            max_expense = None
            if proj_expenses:
                max_expense = max(proj_expenses, key=lambda x: int(x.get("jumlah", 0) or 0))
            
            finished_cards.append({
                "name": _project_display_name(proj_name),
                "metrics": metrics,
                "timeline": timeline,
                "max_expense": max_expense,
            })
        
        company_details[comp] = {
            "summary": comp_summary,
            "prev_summary": prev_comp_summary,
            "income_txs": income_txs,
            "expense_txs": expense_txs,
            "salary_txs": salary_txs,
            "finished_cards": finished_cards,
        }
    
    return {
        "mode": "monthly",
        "year": year,
        "month": month,
        "period_label": period_label,
        "generated_on": format_generated_on(),
        "summary": summary,
        "prev_summary": prev_summary,
        "income_share": income_share,
        "income_by_company": income_by_company,
        "finished_projects": finished_projects,
        "company_details": company_details,
    }

def _build_context_range(start_dt: datetime, end_dt: datetime) -> Dict:
    """Build context for range report (same as original)."""
    all_txs = _get_all_transactions()
    period_txs = _filter_period(all_txs, start_dt, end_dt)
    
    if not period_txs:
        period_label = f"{start_dt.date()} - {end_dt.date()}"
        raise PDFNoDataError(period_label)
    
    summary = _summarize_period(period_txs)
    
    company_txs_map = {comp: [] for comp in COMPANY_KEYS}
    for tx in period_txs:
        comp = _company_from_tx(tx)
        if comp and comp in company_txs_map:
            company_txs_map[comp].append(tx)
    
    income_by_company = {}
    for comp in COMPANY_KEYS:
        comp_sum = _summarize_company(company_txs_map[comp])
        income_by_company[comp] = comp_sum["income_total"]
    
    total_income = sum(income_by_company.values())
    income_share = {}
    for comp in COMPANY_KEYS:
        if total_income > 0:
            income_share[comp] = (income_by_company[comp] / total_income) * 100
        else:
            income_share[comp] = 0.0
    
    finished_projects = _finished_projects_by_company(period_txs)
    
    period_label = f"{start_dt.strftime('%d %b %y')} - {end_dt.strftime('%d %b %y')}"
    
    return {
        "mode": "range",
        "generated_on": format_generated_on(),
        "summary": summary,
        "income_share": income_share,
        "income_by_company": income_by_company,
        "finished_projects": finished_projects,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "period_label": period_label,
    }


# =============================================================================
# Drawing primitives (REDESIGNED - Professional UI toolkit)
# =============================================================================

@dataclass
class UI:
    """Redesigned UI configuration with improved spacing and sizes."""
    fonts: Dict[str, str]
    margin: float = 40          # Increased from 36
    radius: float = 18          # Increased from 16 - rounder corners
    shadow_dx: float = 0        
    shadow_dy: float = -3       # Slightly reduced offset
    shadow_alpha: float = 0.05  # Slightly reduced primary alpha

def _set_alpha(c: canvas.Canvas, fill: Optional[float] = None, stroke: Optional[float] = None):
    if fill is not None and hasattr(c, "setFillAlpha"):
        try:
            c.setFillAlpha(fill)  # type: ignore
        except Exception:
            pass
    if stroke is not None and hasattr(c, "setStrokeAlpha"):
        try:
            c.setStrokeAlpha(stroke)  # type: ignore
        except Exception:
            pass

def _draw_card(c: canvas.Canvas, ui: UI, x: float, y: float, w: float, h: float,
               fill=None, stroke=None, shadow: bool = True, accent_top: Optional[tuple] = None):
    """
    REDESIGNED: Professional card with softer, multi-layer shadow.
    """
    if fill is None:
        fill = THEME["card"]
    
    if shadow:
        # Layer 1: Large ambient shadow (furthest, softest)
        c.saveState()
        _set_alpha(c, fill=0.02, stroke=0)  # Reduced from 0.03
        c.setFillColor(THEME["shadow"])
        c.roundRect(x - 1, y - 6, w + 2, h + 3, ui.radius + 3, stroke=0, fill=1)
        c.restoreState()
        
        # Layer 2: Medium shadow
        c.saveState()
        _set_alpha(c, fill=0.04, stroke=0)  # Reduced from 0.05
        c.setFillColor(THEME["shadow"])
        c.roundRect(x, y - 3, w, h + 1, ui.radius + 1, stroke=0, fill=1)
        c.restoreState()
        
        # Layer 3: Tight shadow (closest, most visible)
        c.saveState()
        _set_alpha(c, fill=ui.shadow_alpha, stroke=0)
        c.setFillColor(THEME["shadow"])
        c.roundRect(x, y - 1, w, h, ui.radius, stroke=0, fill=1)
        c.restoreState()

    # Main card - no border for cleaner look
    c.saveState()
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, ui.radius, stroke=0, fill=1)
    c.restoreState()
    
    # Optional top accent bar
    if accent_top:
        accent_color, accent_h = accent_top
        c.saveState()
        c.setFillColor(accent_color)
        p = c.beginPath()
        p.moveTo(x + ui.radius, y + h)
        p.lineTo(x + w - ui.radius, y + h)
        p.arcTo(x + w - ui.radius, y + h - ui.radius, x + w, y + h, 0, 90)
        p.lineTo(x + w, y + h - accent_h)
        p.lineTo(x, y + h - accent_h)
        p.lineTo(x, y + h - ui.radius)
        p.arcTo(x, y + h - ui.radius, x + ui.radius, y + h, 90, 90)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        c.restoreState()


def _fit_ellipsis(text: str, font_name: str, font_size: float, max_w: float) -> str:
    """Same as original - works fine."""
    t = text or ""
    if stringWidth(t, font_name, font_size) <= max_w:
        return t
    ell = "..."
    if stringWidth(ell, font_name, font_size) > max_w:
        return ""
    lo, hi = 0, len(t)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = t[:mid].rstrip() + ell
        if stringWidth(cand, font_name, font_size) <= max_w:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best or ell

def _wrap_lines(text: str, font_name: str, font_size: float, max_w: float, max_lines: int) -> List[str]:
    """Same as original - works fine."""
    t = (text or "").strip()
    if not t:
        return []

    words = t.split()
    lines: List[str] = []
    cur = ""

    def flush(line: str):
        if line.strip():
            lines.append(line.strip())

    for w in words:
        if stringWidth(w, font_name, font_size) > max_w:
            flush(cur)
            lines.append(_fit_ellipsis(w, font_name, font_size, max_w))
            cur = ""
            if len(lines) >= max_lines:
                break
            continue

        cand = (cur + " " + w).strip() if cur else w
        if stringWidth(cand, font_name, font_size) <= max_w:
            cur = cand
        else:
            flush(cur)
            cur = w
            if len(lines) >= max_lines:
                break

    if len(lines) < max_lines and cur:
        lines.append(cur.strip())

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if len(lines) == max_lines:
        joined = " ".join(lines)
        if joined != t:
            lines[-1] = _fit_ellipsis(lines[-1], font_name, font_size, max_w)

    return lines

def _draw_text(c: canvas.Canvas, font: str, size: float, color, x: float, y: float, text: str, align: str = "left"):
    """Same as original."""
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "right":
        c.drawRightString(x, y, text)
    elif align == "center":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)

def _fit_font_size(text: str, font: str, max_size: float, min_size: float, max_w: float) -> float:
    """Same as original."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_w:
        size -= 0.5
    return size

def _draw_text_fit(c: canvas.Canvas, font: str, max_size: float, min_size: float, color, x: float, y: float, text: str, max_w: float, align: str = "left"):
    """Same as original."""
    size = _fit_font_size(text, font, max_size, min_size, max_w)
    _draw_text(c, font, size, color, x, y, text, align=align)

def _draw_footer(c: canvas.Canvas, ui: UI, page_w: float):
    """REDESIGNED: Slightly larger footer text."""
    y = 16  # Increased from 14
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted2"], ui.margin, y, "Finance Bot • Confidential")
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted2"], page_w - ui.margin, y, f"Page {c.getPageNumber()}", align="right")


# =============================================================================
# Components (REDESIGNED)
# =============================================================================

def _draw_header_monthly(c: canvas.Canvas, ui: UI, ctx: Dict, page_w: float, page_h: float, logo_path: Optional[str]):
    """REDESIGNED: Cleaner header with better typography."""
    header_h = 190
    left_w = 427

    # Header background
    c.saveState()
    c.setFillColor(THEME["teal"])
    c.rect(0, page_h - header_h, left_w, header_h, fill=1, stroke=0)

    # Subtle geometric accents
    _set_alpha(c, fill=0.08)  # Slightly reduced from 0.10
    c.setFillColor(colors.white)
    c.circle(left_w - 60, page_h - 40, 36, stroke=0, fill=1)
    c.circle(left_w - 120, page_h - 90, 22, stroke=0, fill=1)
    c.restoreState()

    # Logo
    if logo_path and os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, 30, page_h - 78, width=120, height=40, mask="auto")
        except Exception:
            pass

    # Texts - REDESIGNED with better sizes
    _draw_text(c, ui.fonts["italic"], 10.5, THEME["white"], 140, page_h - 30, f"Generated on {ctx['generated_on']}")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, page_h - 74, "Financial")  # Increased from 30
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, page_h - 114, "Report")

    # Period label (right) - REDESIGNED with better sizes
    month_part, year_part = ctx["period_label"].split()
    _draw_text(c, ui.fonts["bold"], 36, THEME["teal"], left_w + 18, page_h - 74, month_part)  # Increased from 34
    _draw_text(c, ui.fonts["bold"], 36, THEME["teal"], left_w + 18, page_h - 114, year_part)

def _draw_header_range(c: canvas.Canvas, ui: UI, ctx: Dict, page_w: float, page_h: float, logo_path: Optional[str]):
    """REDESIGNED: Similar improvements to range header."""
    header_h = 190
    left_w = 427

    c.saveState()
    c.setFillColor(THEME["teal"])
    c.rect(0, page_h - header_h, left_w, header_h, fill=1, stroke=0)

    _set_alpha(c, fill=0.08)
    c.setFillColor(colors.white)
    c.circle(left_w - 60, page_h - 40, 36, stroke=0, fill=1)
    c.circle(left_w - 120, page_h - 90, 22, stroke=0, fill=1)
    c.restoreState()

    if logo_path and os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, 30, page_h - 78, width=120, height=40, mask="auto")
        except Exception:
            pass

    _draw_text(c, ui.fonts["italic"], 10.5, THEME["white"], 140, page_h - 30, f"Generated on {ctx['generated_on']}")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, page_h - 74, "Financial")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, page_h - 114, "Report")

    # Range info
    start_text = ctx["start_dt"].strftime("%d-%m-%y")
    end_text = ctx["end_dt"].strftime("%d-%m-%y")

    _draw_text(c, ui.fonts["bold"], 22, THEME["teal"], left_w + 18, page_h - 66, "Periodical Audit")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], left_w + 18, page_h - 86, "Dalam rentang waktu")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["text"], left_w + 18, page_h - 106, f"{start_text} (00:00)")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], left_w + 18, page_h - 122, "hingga")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["text"], left_w + 18, page_h - 138, f"{end_text} (00:00)")

def _draw_kpi_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float,
                   label: str, amount: int, accent, subnote: Optional[str] = None):
    """
    REDESIGNED: Bigger text, better spacing, cleaner styling.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)

    # Top accent bar - 5px high now (was 4px)
    accent_h = 5
    c.saveState()
    c.setFillColor(accent)
    c.roundRect(x, y + h - accent_h, w, accent_h, 2, stroke=0, fill=1)
    c.setFillColor(THEME["card"])
    c.rect(x, y + h - accent_h, w, 1, stroke=0, fill=1)
    c.restoreState()

    # Label - REDESIGNED: bigger, better positioned
    _draw_text(c, ui.fonts["semibold"], 11, THEME["muted"], x + 20, y + h - 28, label.upper())

    # Currency + number - REDESIGNED: much bigger for impact
    num_color = accent if accent != THEME["text"] else THEME["text"]
    if label.lower().startswith("profit") and amount < 0:
        num_color = THEME["danger"]
    
    _draw_text(c, ui.fonts["regular"], 12, THEME["muted2"], x + 20, y + h - 52, "Rp")
    amt_text = format_number(amount)
    amt_max_w = w - 64  # More space for the number
    # BIGGER SIZE: 28pt max (was 24pt)
    _draw_text_fit(c, ui.fonts["bold"], 28, 18, num_color, x + 44, y + h - 58, amt_text, amt_max_w, align="left")

    # Subnote - better spacing
    if subnote:
        lines = _wrap_lines(subnote, ui.fonts["regular"], 10, w - 40, max_lines=2)
        yy = y + 16
        for i, line in enumerate(lines):
            _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], x + 20, yy + (i * 14), line)


def _draw_comparison_chart(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float,
                           curr: Dict, prev: Dict):
    """
    REDESIGNED: Cleaner comparison table with better typography and spacing.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)

    # Title - REDESIGNED: bigger
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x + 20, y + h - 24, "Perbandingan Bulan Lalu")

    # Column layout - more generous spacing
    padding = 20
    col_label = 100  # Increased from 90
    col_prev = 115   # Increased from 110
    col_now = 115    # Increased from 110
    col_delta = w - (col_label + col_prev + col_now) - 2 * padding - 10

    # Header row - REDESIGNED: bigger text
    header_y = y + h - 46  # More space from title
    _draw_text(c, ui.fonts["semibold"], 10, THEME["muted"], x + padding, header_y, "Item")
    _draw_text(c, ui.fonts["semibold"], 10, THEME["muted"], x + padding + col_label + col_prev - 4, header_y, "Bulan lalu", align="right")
    _draw_text(c, ui.fonts["semibold"], 10, THEME["muted"], x + padding + col_label + col_prev + col_now - 4, header_y, "Selisih", align="right")
    _draw_text(c, ui.fonts["semibold"], 10, THEME["muted"], x + w - padding, header_y, "Bulan ini", align="right")

    rows = [
        ("Omset", "income_total", THEME["accent"], "income"),
        ("Pengeluaran", "expense_total", THEME["warning"], "expense"),
        ("Profit", "profit", THEME["success"], "profit"),
    ]

    row_h = 30  # Increased from 26
    start_y = header_y - 20
    for idx, (label, key, color_now, delta_key) in enumerate(rows):
        cy = start_y - idx * row_h
        curr_val = int(curr.get(key, 0) or 0)
        prev_val = int(prev.get(key, 0) or 0)

        # Label - REDESIGNED: bigger
        _draw_text(c, ui.fonts["semibold"], 11, THEME["text"], x + padding, cy, label)

        # Values - REDESIGNED: bigger text
        _draw_text_fit(c, ui.fonts["regular"], 10.5, 9, THEME["muted"], 
                      x + padding + col_label + col_prev - 4, cy, 
                      format_currency(prev_val), col_prev - 8, align="right")
        
        _draw_text_fit(c, ui.fonts["bold"], 11, 9, THEME["text"], 
                      x + w - padding, cy, 
                      format_currency(curr_val), col_now - 8, align="right")

        # Delta pill - REDESIGNED: bigger
        pill_text, pill_color = _delta_pill(delta_key, curr_val, prev_val)
        pw = max(48, stringWidth(pill_text, ui.fonts["bold"], 9.5) + 20)  # Increased
        ph = 18  # Increased from 16
        px = x + padding + col_label + col_prev + col_now - pw
        c.setFillColor(pill_color)
        c.roundRect(px, cy - 7, pw, ph, 9, stroke=0, fill=1)
        _draw_text(c, ui.fonts["bold"], 9.5, THEME["white"], px + pw / 2, cy - 2.5, pill_text, align="center")

        # Row divider - lighter
        if idx < len(rows) - 1:
            c.setStrokeColor(THEME["border_light"])  # Lighter divider
            c.setLineWidth(1)
            c.line(x + padding, cy - 14, x + w - padding, cy - 14)


def _draw_income_share_chart(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, items: List[Tuple[str, float, int]]):
    """
    REDESIGNED: Bigger bars, better spacing, cleaner layout.
    """
    title_h = 22  # Increased from 18
    bar_h = 14    # Increased from 12
    gap = 16      # Increased from 14

    _draw_text(c, ui.fonts["bold"], 13, THEME["text"], x, y_top - 4, "Grafik Pemasukkan")  # Bigger title
    y = y_top - title_h

    label_w = 100   # Increased from 90
    value_w = 48    # Increased from 42
    amount_w = 100  # Increased from 92
    bar_w = max(60, w - label_w - value_w - amount_w - 16)
    bar_x = x + label_w
    value_x = x + w - 4

    for i, (comp, pct, amt) in enumerate(items):
        yy = y - (i * (bar_h + gap))
        label = COMPANY_DISPLAY_COVER.get(comp, comp)
        _draw_text(c, ui.fonts["semibold"], 10.5, THEME["text"], x, yy + 2, label)  # Bigger labels

        # Track background
        c.setFillColor(THEME["track"])
        c.roundRect(bar_x, yy, bar_w, bar_h, 7, stroke=0, fill=1)  # Rounder corners

        # Fill bar
        fill_w = bar_w * (pct / 100.0)
        c.setFillColor(COMPANY_COLOR.get(comp, THEME["accent"]))
        c.roundRect(bar_x, yy, max(4, fill_w), bar_h, 7, stroke=0, fill=1)

        # Percentage - REDESIGNED: bigger
        _draw_text(c, ui.fonts["bold"], 10.5, THEME["text"], value_x, yy + 2, f"{pct:.0f}%", align="right")
        # Amount - REDESIGNED: bigger
        _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted2"], value_x, yy - 10, f"Rp {format_number(amt)}", align="right")


def _draw_finished_projects_cover(c: canvas.Canvas, ui: UI, ctx: Dict,
                                 page_w: float, y_top: float, title: str, note: str):
    """
    REDESIGNED: Better spacing and typography for project section.
    """
    card_x = ui.margin
    card_w = page_w - ui.margin * 2
    card_h = 340  # Increased from 320 for more space
    y = y_top - card_h

    _draw_card(c, ui, card_x, y, card_w, card_h, shadow=True)

    pad = 20  # Increased from 16
    accent_size = 16  # Increased from 14
    c.setFillColor(THEME["accent"])
    c.roundRect(card_x + pad, y + card_h - pad - accent_size, accent_size, accent_size, 5, stroke=0, fill=1)
    _draw_text(c, ui.fonts["bold"], 16, THEME["text"], card_x + pad + accent_size + 12, y + card_h - pad - 3, title)  # Bigger

    # Note
    note_lines = _wrap_lines(note, ui.fonts["regular"], 10.5, card_w - 2 * pad, max_lines=2)  # Bigger text
    note_y = y + card_h - pad - 26
    for i, line in enumerate(note_lines):
        _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], card_x + pad, note_y - (i * 14), line)

    # Chart area
    chart_h = 92  # Increased from 88
    chart_y0 = y + pad
    chart_top = chart_y0 + chart_h

    # Divider
    c.setStrokeColor(THEME["border"])
    c.setLineWidth(1)
    c.line(card_x + pad, chart_top + 8, card_x + card_w - pad, chart_top + 8)

    # Columns
    body_top = note_y - (len(note_lines) * 14) - 14
    body_bottom = chart_top + 14
    col_w = (card_w - 2 * pad) / 4.0
    col_x0 = card_x + pad
    col_y0 = body_top - 8

    for idx, comp in enumerate(COMPANY_KEYS):
        cx = col_x0 + idx * col_w

        if idx > 0:
            c.setStrokeColor(THEME["border_light"])
            c.setLineWidth(1)
            c.line(cx, body_bottom, cx, body_top)

        _draw_text(c, ui.fonts["semibold"], 11.5, THEME["text"], cx + 10, col_y0, COMPANY_DISPLAY_COVER.get(comp, comp))  # Bigger
        count = len(ctx["finished_projects"].get(comp, []))
        _draw_text(c, ui.fonts["bold"], 24, COMPANY_COLOR.get(comp, THEME["accent"]), cx + 10, col_y0 - 28, str(count))  # Bigger

        projects = ctx["finished_projects"].get(comp, []) or []
        display = [_project_display_name(p) or p for p in projects]

        yy = col_y0 - 52
        line_h = 12
        if not display:
            _draw_text(c, ui.fonts["regular"], 10, THEME["muted2"], cx + 10, yy, "Tidak ada project")
        else:
            drawn = 0
            for name in display:
                lines = _wrap_lines(name, ui.fonts["regular"], 10, col_w - 20, max_lines=2)  # Bigger text
                if not lines:
                    lines = ["-"]
                needed_h = len(lines) * line_h + 6
                if yy - needed_h < body_bottom:
                    break
                _draw_text(c, ui.fonts["regular"], 10, THEME["text"], cx + 10, yy, f"• {lines[0]}")
                if len(lines) > 1:
                    _draw_text(c, ui.fonts["regular"], 10, THEME["text"], cx + 22, yy - line_h, lines[1])
                    yy -= (line_h * 2)
                else:
                    yy -= line_h
                yy -= 6
                drawn += 1

            remaining = len(display) - drawn
            if remaining > 0 and yy - 14 > body_bottom:
                _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], cx + 10, yy - 6, f"+{remaining} lainnya")

    chart_items = [(c, ctx["income_share"].get(c, 0.0), ctx.get("income_by_company", {}).get(c, 0)) for c in COMPANY_KEYS]
    _draw_income_share_chart(c, ui, card_x + pad, chart_y0 + chart_h - 8, card_w - 2 * pad, chart_items)


# =============================================================================
# Company page components (REDESIGNED)
# =============================================================================

def _draw_company_header(c: canvas.Canvas, ui: UI, ctx: Dict, company: str, page_w: float, page_h: float, header_h: float = 150):
    """REDESIGNED: Better typography."""
    color = COMPANY_COLOR.get(company, THEME["teal"])
    c.setFillColor(color)
    c.rect(0, page_h - header_h, page_w, header_h, fill=1, stroke=0)

    # Text - REDESIGNED: bigger
    _draw_text(c, ui.fonts["italic"], 10.5, THEME["white"], ui.margin, page_h - 28, f"Generated on {ctx['generated_on']}")
    _draw_text(c, ui.fonts["bold"], 28, THEME["white"], ui.margin, page_h - 72, COMPANY_DISPLAY.get(company, company))  # Bigger

    # Period label
    month_part, year_part = ctx["period_label"].split()
    _draw_text(c, ui.fonts["bold"], 24, THEME["white"], page_w - ui.margin, page_h - 58, month_part, align="right")  # Bigger
    _draw_text(c, ui.fonts["bold"], 24, THEME["white"], page_w - ui.margin, page_h - 90, year_part, align="right")


def _draw_tx_list_card(
    c: canvas.Canvas,
    ui: UI,
    x: float,
    y_top: float,
    w: float,
    title: str,
    items: List[Dict],
    kind_color,
    max_items: Optional[int] = None,
    h: float = 200,  # Increased from 190
):
    """
    REDESIGNED: Better spacing and typography for transaction lists.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    
    # Title - REDESIGNED: bigger
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x + 20, y + h - 26, title)

    # Accent bar
    c.saveState()
    c.setFillColor(kind_color)
    c.roundRect(x + 20, y + h - 40, 28, 4, 2, stroke=0, fill=1)  # Longer bar
    c.restoreState()

    if not items:
        _draw_text(c, ui.fonts["regular"], 11, THEME["muted2"], x + 20, y + h - 58, "Tidak ada data")
        return

    font_name = ui.fonts["regular"]
    font_size = 10.5  # Increased from 9.5
    amount_font = ui.fonts["semibold"]
    amount_size = 11  # Increased from 10.5

    padding_x = 20
    max_display = max_items if max_items is not None else len(items)
    sample = items[:max_display]

    yy = y + h - 52  # Adjusted for new spacing
    drawn = 0

    for i, tx in enumerate(sample):
        desc = (tx.get("keterangan") or "-").strip()
        if not desc:
            desc = "-"

        prefix = f"{i + 1}."
        prefix_w = stringWidth(prefix + " ", font_name, font_size)
        avail_w = w - 2 * padding_x - prefix_w - 100  # More space for amount

        wrapped = _wrap_lines(desc, font_name, font_size, avail_w, max_lines=2)
        if not wrapped:
            wrapped = ["-"]

        line_h = 15  # Increased from 14
        row_h = line_h * len(wrapped) + 12  # More spacing
        line_y = yy - row_h

        if line_y < y + 16:
            break

        # Line 1
        _draw_text(c, font_name, font_size, THEME["text"], x + padding_x, line_y + row_h - 20, f"{prefix} {wrapped[0]}")
        # Line 2
        if len(wrapped) > 1:
            _draw_text(c, font_name, font_size, THEME["muted"], x + padding_x + prefix_w, line_y + row_h - 35, wrapped[1])

        # Amount
        amt = int(tx.get("jumlah", 0) or 0)
        _draw_text(c, amount_font, amount_size, THEME["text"], x + w - padding_x, line_y + row_h - 20, f"Rp {format_number(amt)}", align="right")

        drawn += 1
        yy = line_y

        # Divider - lighter
        if i < len(sample) - 1:
            c.saveState()
            c.setStrokeColor(THEME["border_light"])
            c.setLineWidth(1)
            c.line(x + padding_x, yy + 6, x + w - padding_x, yy + 6)
            c.restoreState()

    remaining = len(items) - drawn
    if remaining > 0 and yy - 20 > y + 14:
        _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], x + padding_x, yy - 12, f"+{remaining} lainnya")


def _draw_insight_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, company_details: Dict, h: float = 200):
    """
    REDESIGNED: Better spacing and typography for insights.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    
    # Title - REDESIGNED: bigger
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x + 20, y + h - 26, "Insight")
    c.saveState()
    c.setFillColor(THEME["accent"])
    c.roundRect(x + 20, y + h - 40, 24, 4, 2, stroke=0, fill=1)
    c.restoreState()

    lines: List[str] = []
    exp = company_details.get("expense_txs") or []
    sal = company_details.get("salary_txs") or []

    if exp:
        top = exp[0]
        lines.append(f"Pengeluaran terbesar bulan ini: {_fit_ellipsis(top.get('keterangan',''), ui.fonts['regular'], 10.5, w-240)} (Rp {format_number(int(top.get('jumlah',0) or 0))})")
    else:
        lines.append("Pengeluaran terbesar bulan ini: Tidak ada data")

    if sal:
        smax = sal[0]
        smin = sal[-1] if len(sal) > 1 else sal[0]
        lines.append(f"Gaji terbesar: {_fit_ellipsis(smax.get('keterangan',''), ui.fonts['regular'], 10.5, w-200)} (Rp {format_number(int(smax.get('jumlah',0) or 0))})")
        lines.append(f"Gaji terkecil: {_fit_ellipsis(smin.get('keterangan',''), ui.fonts['regular'], 10.5, w-200)} (Rp {format_number(int(smin.get('jumlah',0) or 0))})")
    else:
        lines.append("Gaji terbesar: Tidak ada data")
        lines.append("Gaji terkecil: Tidak ada data")

    cards = company_details.get("finished_cards") or []
    if cards:
        best = max(cards, key=lambda x: int(x["metrics"]["profit"]))
        worst = min(cards, key=lambda x: int(x["metrics"]["profit"]))
        lines.append(f"Finished project terbaik: {_fit_ellipsis(best['name'], ui.fonts['regular'], 10.5, w-240)} (Rp {format_number(int(best['metrics']['profit']))})")
        lines.append(f"Finished project terendah: {_fit_ellipsis(worst['name'], ui.fonts['regular'], 10.5, w-240)} (Rp {format_number(int(worst['metrics']['profit']))})")
    else:
        lines.append("Finished project terbaik: Tidak ada data")
        lines.append("Finished project terendah: Tidak ada data")

    # Draw lines - REDESIGNED: better spacing
    yy = y + h - 56
    max_lines = 5 if h >= 200 else 4
    for i, line in enumerate(lines[:max_lines], start=0):
        _draw_text(c, ui.fonts["regular"], 10.5, THEME["text"], x + 20, yy - i * 24, _fit_ellipsis(line, ui.fonts["regular"], 10.5, w - 40))


def _draw_project_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float,
                       idx: int, company: str, proj: Dict):
    """
    REDESIGNED: Better spacing and typography for project cards.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)

    accent = COMPANY_COLOR.get(company, THEME["accent"])
    
    # Top accent bar - taller
    accent_h = 5  # Increased from 4
    c.saveState()
    c.setFillColor(accent)
    c.roundRect(x, y + h - accent_h, w, accent_h + 2, 2, stroke=0, fill=1)
    c.setFillColor(THEME["card"])
    c.rect(x, y + h - accent_h, w, 1, stroke=0, fill=1)
    c.restoreState()

    # Name - REDESIGNED: bigger
    name = proj.get("name", "Project")
    name = _fit_ellipsis(f"{idx}. {name}", ui.fonts["bold"], 14, w - 200)  # Bigger
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x + 22, y + h - 30, name)

    metrics = proj.get("metrics", {}) or {}
    profit = int(metrics.get("profit", 0) or 0)
    margin = int(metrics.get("margin_pct", 0) or 0)

    profit_color = THEME["success"] if profit >= 0 else THEME["danger"]
    _draw_text(c, ui.fonts["semibold"], 11, THEME["muted"], x + w - 22, y + h - 28, "Profit Kotor", align="right")
    profit_text = f"Rp {format_number(profit)}  ({margin}%)"
    _draw_text_fit(
        c,
        ui.fonts["bold"],
        14,  # Increased from 13
        10,
        profit_color,
        x + w - 22,
        y + h - 46,
        profit_text,
        190,
        align="right",
    )

    timeline = proj.get("timeline", {}) or {}
    start_dt = timeline.get("start")
    finish_dt = timeline.get("finish")
    start_txt = start_dt.strftime("%d %b %Y") if isinstance(start_dt, datetime) else "-"
    finish_txt = finish_dt.strftime("%d %b %Y") if isinstance(finish_dt, datetime) else "-"

    # Timeline - REDESIGNED: bigger text
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], x + 22, y + h - 52, f"Mulai: {start_txt}")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], x + 22, y + h - 68, f"Selesai: {finish_txt}")

    # Metrics grid
    col1_x = x + 22
    col_w = (w - 44) / 4.0

    def metric_cell(ix: int, label: str, value: int, y0: float):
        cx = col1_x + ix * col_w
        _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], cx, y0, label)  # Bigger
        val_text = f"Rp {format_number(value)}"
        _draw_text_fit(
            c,
            ui.fonts["bold"],
            12,  # Increased from 11
            9.5,
            THEME["text"],
            cx + col_w - 2,
            y0 - 16,
            val_text,
            col_w - 6,
            align="right",
        )

    y_row1 = y + 62  # More space
    metric_cell(0, "Nilai", int(metrics.get("total_income", 0) or 0), y_row1)
    metric_cell(1, "DP", int(metrics.get("dp", 0) or 0), y_row1)
    metric_cell(2, "DP 2", int(metrics.get("dp2", 0) or 0), y_row1)
    metric_cell(3, "Pelunasan", int(metrics.get("pelunasan", 0) or 0), y_row1)

    y_row2 = y + 32
    metric_cell(0, "Pengeluaran", int(metrics.get("total_expense", 0) or 0), y_row2)
    metric_cell(1, "Gaji", int(metrics.get("total_salary", 0) or 0), y_row2)

    max_exp = proj.get("max_expense")
    if max_exp:
        desc = _fit_ellipsis(max_exp.get("keterangan", ""), ui.fonts["regular"], 10, col_w * 2 - 12)  # Bigger
        amt = int(max_exp.get("jumlah", 0) or 0)
        cx = col1_x + 2 * col_w
        _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], cx, y_row2, "Pengeluaran Terbesar")
        _draw_text(c, ui.fonts["regular"], 10, THEME["text"], cx, y_row2 - 14, desc)
        _draw_text(c, ui.fonts["bold"], 12, THEME["text"], cx + col_w * 2 - 10, y_row2 - 16, f"Rp {format_number(amt)}", align="right")
    else:
        cx = col1_x + 2 * col_w
        _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], cx, y_row2, "Pengeluaran Terbesar")
        _draw_text(c, ui.fonts["regular"], 10, THEME["muted2"], cx, y_row2 - 16, "-")

    # Divider - lighter
    c.saveState()
    c.setStrokeColor(THEME["border_light"])
    c.setLineWidth(1)
    c.line(x + 22, y + h - 80, x + w - 22, y + h - 80)
    c.restoreState()


# =============================================================================
# Page drawing functions (using redesigned components)
# =============================================================================

def draw_cover_monthly(c: canvas.Canvas, ui: UI, ctx: Dict, logo_path: Optional[str] = None):
    """Draw monthly cover page (A4) - REDESIGNED."""
    page_w, page_h = A4
    
    # Background
    c.setFillColor(THEME["bg"])
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    
    # Header
    _draw_header_monthly(c, ui, ctx, page_w, page_h, logo_path)
    
    y = page_h - 190 - 28  # Below header with more space
    
    # KPI row - REDESIGNED with more space
    kpi_h = 100  # Increased from 92
    gap = 18     # Increased from 14
    content_x = ui.margin
    content_w = page_w - 2 * ui.margin
    kpi_w = (content_w - 2 * gap) / 3.0
    
    summary = ctx["summary"]
    prev = ctx["prev_summary"]
    
    office_note = f"(Pengeluaran Kantor Rp {format_number(int(summary['office_expense']))})"
    
    _draw_kpi_card(c, ui, content_x + 0 * (kpi_w + gap), y, kpi_w, kpi_h, 
                   "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(c, ui, content_x + 1 * (kpi_w + gap), y, kpi_w, kpi_h, 
                   "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"], subnote=office_note)
    _draw_kpi_card(c, ui, content_x + 2 * (kpi_w + gap), y, kpi_w, kpi_h, 
                   "Profit", int(summary["profit"]), THEME["teal"])
    
    y -= (kpi_h + 28)  # More spacing
    
    # Delta pills row - REDESIGNED
    pill_y = y
    for i, (label_key, label_text, curr_key) in enumerate([
        ("income", "Bulan lalu", "income_total"),
        ("expense", "Bulan lalu", "expense_total"),
        ("profit", "Bulan lalu", "profit"),
    ]):
        pill_x = content_x + i * (kpi_w + gap)
        curr_val = int(summary[curr_key])
        prev_val = int(prev[curr_key])
        
        _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], pill_x + 20, pill_y, "Bulan lalu")
        _draw_text(c, ui.fonts["semibold"], 12, THEME["text"], pill_x + 20, pill_y - 18, format_number(prev_val))
        
        pill_text, pill_color = _delta_pill(label_key, curr_val, prev_val)
        pw = max(50, stringWidth(pill_text, ui.fonts["bold"], 10) + 22)
        ph = 20
        c.setFillColor(pill_color)
        c.roundRect(pill_x + 20, pill_y - 46, pw, ph, 10, stroke=0, fill=1)
        _draw_text(c, ui.fonts["bold"], 10, THEME["white"], pill_x + 20 + pw / 2, pill_y - 40, pill_text, align="center")
    
    y -= 70  # More spacing
    
    # Finished projects section - REDESIGNED
    _draw_finished_projects_cover(
        c, ui, ctx, page_w, y,
        "Project yang Selesai Bulan ini",
        "Adalah Project, yang telah tuntas pada bulan ini. Untuk mulainya tidak harus bulan ini."
    )
    
    _draw_footer(c, ui, page_w)


def draw_cover_periodical(c: canvas.Canvas, ui: UI, ctx: Dict, logo_path: Optional[str] = None):
    """Draw periodical audit cover page (A4) - REDESIGNED."""
    page_w, page_h = A4
    
    c.setFillColor(THEME["bg"])
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    
    _draw_header_range(c, ui, ctx, page_w, page_h, logo_path)
    
    y = page_h - 190 - 28
    
    kpi_h = 100
    gap = 18
    content_x = ui.margin
    content_w = page_w - 2 * ui.margin
    kpi_w = (content_w - 2 * gap) / 3.0
    
    summary = ctx["summary"]
    office_note = f"(Pengeluaran Kantor Rp {format_number(int(summary['office_expense']))})"
    
    _draw_kpi_card(c, ui, content_x + 0 * (kpi_w + gap), y, kpi_w, kpi_h, 
                   "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(c, ui, content_x + 1 * (kpi_w + gap), y, kpi_w, kpi_h, 
                   "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"], subnote=office_note)
    _draw_kpi_card(c, ui, content_x + 2 * (kpi_w + gap), y, kpi_w, kpi_h, 
                   "Profit", int(summary["profit"]), THEME["teal"])
    
    y -= (kpi_h + 28)
    
    _draw_finished_projects_cover(
        c, ui, ctx, page_w, y,
        "Project yang Selesai dalam Periode ini",
        "Adalah Project yang tuntas dalam rentang waktu yang dipilih."
    )
    
    _draw_footer(c, ui, page_w)


def _estimate_company_page_height(ui: UI, company_details: Dict, base_h: float = 1700) -> float:
    """Estimate height needed for company page - REDESIGNED with more space."""
    cards = company_details.get("finished_cards") or []
    card_h = 128  # Increased from 118
    card_gap = 14  # Increased from 12
    n_cards = len(cards)
    
    if n_cards == 0:
        return base_h
    
    extra_h = n_cards * (card_h + card_gap) + 60
    return base_h + extra_h


def draw_company_page(c: canvas.Canvas, ui: UI, ctx: Dict, company: str, page_h: float):
    """Draw company page (tall custom page) - REDESIGNED."""
    page_w = A4[0]
    
    c.setFillColor(THEME["bg"])
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    
    _draw_company_header(c, ui, ctx, company, page_w, page_h, header_h=150)
    
    details = ctx["company_details"][company]
    summary = details["summary"]
    prev = details["prev_summary"]
    
    content_x = ui.margin
    content_w = page_w - 2 * ui.margin
    
    # KPI row - REDESIGNED
    y = page_h - 150 - 28
    kpi_h = 100  # Increased from 92
    gap = 18     # Increased from 14
    kpi_w = (content_w - 2 * gap) / 3.0
    
    _draw_kpi_card(c, ui, content_x + 0 * (kpi_w + gap), y, kpi_w, kpi_h, "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(c, ui, content_x + 1 * (kpi_w + gap), y, kpi_w, kpi_h, "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"])
    _draw_kpi_card(c, ui, content_x + 2 * (kpi_w + gap), y, kpi_w, kpi_h, "Profit", int(summary["profit"]), THEME["teal"])
    
    y -= (kpi_h + 24)
    
    # Last month summary + comparison chart - REDESIGNED
    left_w = 260  # Increased from 240
    row_h = 142   # Increased from 132
    
    _draw_card(c, ui, content_x, y - row_h, left_w, row_h, shadow=True)
    _draw_text(c, ui.fonts["bold"], 13, THEME["text"], content_x + 16, y - 22, "Bulan lalu (ringkas)")  # Bigger
    
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], content_x + 16, y - 50, "Omset")
    _draw_text(c, ui.fonts["semibold"], 11.5, THEME["text"], content_x + left_w - 16, y - 50, format_currency(int(prev["income_total"])), align="right")
    
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], content_x + 16, y - 78, "Pengeluaran")
    _draw_text(c, ui.fonts["semibold"], 11.5, THEME["text"], content_x + left_w - 16, y - 78, format_currency(int(prev["expense_total"])), align="right")
    
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], content_x + 16, y - 106, "Profit")
    pcol = THEME["text"] if int(prev["profit"]) >= 0 else THEME["danger"]
    _draw_text(c, ui.fonts["bold"], 11.5, pcol, content_x + left_w - 16, y - 106, format_currency(int(prev["profit"])), align="right")
    
    chart_x = content_x + left_w + 18
    chart_w = content_w - left_w - 18
    _draw_comparison_chart(c, ui, chart_x, y, chart_w, row_h, summary, prev)
    
    y -= (row_h + 24)
    
    # Lists row - REDESIGNED with more space
    col_gap = 20   # Increased from 16
    col_w = (content_w - col_gap) / 2.0
    list_h = 200   # Increased from 190
    
    _draw_tx_list_card(
        c, ui, content_x, y, col_w,
        "List Pemasukan", details["income_txs"], THEME["teal"],
        max_items=None, h=list_h
    )
    _draw_tx_list_card(
        c, ui, content_x + col_w + col_gap, y, col_w,
        "List Pengeluaran", details["expense_txs"], THEME["pink"],
        max_items=None, h=list_h
    )
    
    y -= (list_h + 20)
    
    _draw_tx_list_card(
        c, ui, content_x, y, col_w,
        "List Gaji", details["salary_txs"], COMPANY_COLOR.get(company, THEME["teal"]),
        max_items=None, h=list_h
    )
    _draw_insight_card(c, ui, content_x + col_w + col_gap, y, col_w, details, h=list_h)
    
    y -= (list_h + 28)
    
    # Finished projects section - REDESIGNED
    _draw_text(c, ui.fonts["bold"], 16, THEME["text"], content_x, y, "Finished Projects")  # Bigger
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], content_x, y - 18, "Project yang tuntas pada bulan ini (mulai bisa dari bulan lain).")
    
    y -= 36  # More space
    
    cards = details.get("finished_cards") or []
    if not cards:
        _draw_text(c, ui.fonts["regular"], 11, THEME["muted2"], content_x, y - 10, "Tidak ada project selesai pada bulan ini.")
        _draw_footer(c, ui, page_w)
        return
    
    card_gap = 14  # Increased from 12
    card_h = 128   # Increased from 118
    footer_space = 30
    available_h = y - (ui.margin + footer_space)
    max_cards = max(1, int((available_h + card_gap) // (card_h + card_gap)))
    
    for i, proj in enumerate(cards[:max_cards], start=1):
        _draw_project_card(c, ui, content_x, y, content_w, card_h, i, company, proj)
        y -= (card_h + card_gap)
    
    if len(cards) > max_cards:
        _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], content_x, y - 6, f"+{len(cards) - max_cards} project lainnya tidak ditampilkan (untuk menjaga layout tetap rapi).")
    
    _draw_footer(c, ui, page_w)


# =============================================================================
# PDF generators (same interface as before)
# =============================================================================

def generate_pdf_report_v4_monthly(year: int, month: int, output_dir: Optional[str] = None) -> str:
    """
    Monthly export (REDESIGNED v4):
      - Cover (A4)
      - Company pages (custom tall pages)
    """
    ctx = _build_context_monthly(year, month)
    fonts = register_fonts()
    ui = UI(fonts=fonts)
    
    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    fname = _safe_filename(f"Laporan_Keuangan_{ctx['period_label']}_REDESIGNED") + ".pdf"
    output_path = os.path.join(out_dir, fname)
    
    logo_path = os.getenv("HOLLAWALL_LOGO_PATH")
    
    c = canvas.Canvas(output_path, pagesize=A4)
    draw_cover_monthly(c, ui, ctx, logo_path=logo_path)
    c.showPage()
    
    for comp in COMPANY_KEYS:
        page_h = _estimate_company_page_height(ui, ctx["company_details"][comp], base_h=1700)
        c.setPageSize((A4[0], page_h))
        draw_company_page(c, ui, ctx, comp, page_h=page_h)
        c.showPage()
    
    c.save()
    secure_log("INFO", f"PDF generated (REDESIGNED): {output_path}")
    return output_path

def generate_pdf_report_v4_range(start_dt: datetime, end_dt: datetime, output_dir: Optional[str] = None) -> str:
    """
    Periodical Audit export (REDESIGNED v4):
      - Cover only (A4)
    """
    ctx = _build_context_range(start_dt, end_dt)
    fonts = register_fonts()
    ui = UI(fonts=fonts)
    
    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    fname = _safe_filename(f"Laporan_Keuangan_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}_REDESIGNED") + ".pdf"
    output_path = os.path.join(out_dir, fname)
    
    logo_path = os.getenv("HOLLAWALL_LOGO_PATH")
    
    c = canvas.Canvas(output_path, pagesize=A4)
    draw_cover_periodical(c, ui, ctx, logo_path=logo_path)
    c.save()
    
    secure_log("INFO", f"PDF generated (REDESIGNED): {output_path}")
    return output_path


# Backward-compatible wrappers
def generate_pdf_report(year: int, month: int, output_dir: Optional[str] = None, **kwargs) -> str:
    """Backward-compatible wrapper - uses redesigned version."""
    return generate_pdf_report_v4_monthly(year, month, output_dir=output_dir)


def generate_pdf_from_input(period_input: str, output_dir: Optional[str] = None) -> str:
    """
    Main entry for bot command (REDESIGNED version).
    Accepts:
      - Month input: "2026-01", "januari 2026"
      - Range input: "12-01-2026 - 20-01-2026"
    """
    s = _normalize_user_input(period_input)
    if not s:
        raise PDFInputError(
            "Format perintah kosong.\n"
            "Contoh:\n"
            "• /exportpdf 2026-01\n"
            "• /exportpdf Januari 2026\n"
            "• /exportpdf 12-01-2026 - 20-01-2026"
        )
    
    rng = parse_range_input(s)
    if rng:
        start_dt, end_dt = rng
        return generate_pdf_report_v4_range(start_dt, end_dt, output_dir=output_dir)
    
    year, month = parse_month_input(s)
    return generate_pdf_report_v4_monthly(year, month, output_dir=output_dir)


# =============================================================================
# Debug / local run
# =============================================================================

if __name__ == "__main__":
    tests = [
        "2026-01",
        "01-2026",
        "januari 2026",
        "12-01-2026 - 20-01-2026",
        "2026-01-12 - 2026-01-20",
    ]
    for t in tests:
        try:
            s = _normalize_user_input(t)
            rng = parse_range_input(s)
            if rng:
                print("[RANGE]", t, "=>", rng[0].date(), rng[1].date())
            else:
                y, m = parse_month_input(s)
                print("[MONTH]", t, "=>", y, m)
        except Exception as e:
            print("[ERR]", t, "=>", e)