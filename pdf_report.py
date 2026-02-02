# -*- coding: utf-8 -*-
"""
pdf_report.py - Finance Bot PDF Export (Premium Visual v3)

Goal
- Luxury, clean, readable (bigger fonts)
- Stable layout: no clipped text (wrap + ellipsis safeguards)
- Two modes:
  1) Monthly: Cover + 4 company pages (custom tall page like client PDF)
  2) Periodical Audit (range): Cover only

No external deps (besides ReportLab which you already use).
Integrates with:
  from sheets_helper import get_all_data
  from security import secure_log
  from config.wallets import extract_company_prefix, strip_company_prefix

Notes
- This file focuses on the "client style" (Hollawall format).
- Old Platypus/executive report code intentionally removed to avoid conflicts and duplicate charts.
  If you still need the old generator, keep it in a separate module.

Client reference layout: PDF Reports.pdf (cover + company pages). fileciteturn0file0
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
# Theme (Premium minimal + Hollawall palette)
# =============================================================================

THEME = {
    "bg": colors.HexColor("#F8FAFC"),         # Soft light background
    "card": colors.white,
    "card_alt": colors.HexColor("#FAFBFC"),   # Subtle alternate card bg
    "border": colors.HexColor("#E2E8F0"),     # Slate-200 - softer border
    "shadow": colors.HexColor("#0F172A"),     # Slate-900 - deep shadow
    "track": colors.HexColor("#F1F5F9"),      # Slate-100 - subtle track
    "text": colors.HexColor("#1E293B"),       # Slate-800 - professional dark
    "muted": colors.HexColor("#64748B"),      # Slate-500 - readable muted
    "muted2": colors.HexColor("#94A3B8"),     # Slate-400 - lighter muted
    # Primary accent (replaces teal)
    "accent": colors.HexColor("#0EA5E9"),     # Sky-500 - modern blue
    "accent_dark": colors.HexColor("#0284C7"), # Sky-600 - deeper accent
    "accent_light": colors.HexColor("#7DD3FC"), # Sky-300 - light accent
    # Status colors
    "success": colors.HexColor("#10B981"),    # Emerald-500 - positive
    "success_light": colors.HexColor("#D1FAE5"), # Emerald-100 - bg
    "warning": colors.HexColor("#F59E0B"),    # Amber-500 - caution
    "danger": colors.HexColor("#EF4444"),     # Red-500 - negative
    "danger_light": colors.HexColor("#FEE2E2"), # Red-100 - bg
    "white": colors.white,
    # Legacy aliases for compatibility
    "teal": colors.HexColor("#0EA5E9"),       # -> accent
    "teal2": colors.HexColor("#0284C7"),      # -> accent_dark
    "pink": colors.HexColor("#EF4444"),       # -> danger
    "green": colors.HexColor("#10B981"),      # -> success
}


COMPANY_KEYS = ["Hollawall", "Hojja", "Texturin Surabaya", "Texturin Bali"]

COMPANY_DISPLAY = {
    "Hollawall": "Hollawall Mural",
    "Hojja": "Hojja",
    "Texturin Surabaya": "Texturin Surabaya",
    "Texturin Bali": "Texturin Bali",
}
# Cover labels follow the client PDF: Surabaya shown as "Texturin"
COMPANY_DISPLAY_COVER = {
    "Hollawall": "Hollawall",
    "Hojja": "Hojja",
    "Texturin Surabaya": "Texturin",
    "Texturin Bali": "Texturin Bali",
}

COMPANY_COLOR = {
    "Hollawall": colors.HexColor("#0891B2"),      # Cyan-600 - deeper, professional
    "Hojja": colors.HexColor("#059669"),          # Emerald-600 - rich green
    "Texturin Surabaya": colors.HexColor("#B45309"), # Amber-700 - warm brown
    "Texturin Bali": colors.HexColor("#D97706"),  # Amber-600 - golden
}

OFFICE_SHEET_NAME = "Operasional Kantor"

# Keywords used to infer "finish"
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
        # italic is optional; fallback to Helvetica-Oblique
        "italic": ("Inter-Italic", os.path.join(font_dir, "Inter-Italic.ttf")),
    }

    # Default fallback
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
                # keep fallback
                pass

    # If we have Inter-Regular but not italic, keep Helvetica-Oblique
    if ok_any and fonts.get("italic") == "Inter-Italic" and not os.path.exists(candidates["italic"][1]):
        fonts["italic"] = "Helvetica-Oblique"

    return fonts


# =============================================================================
# Safe helpers
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
    # inclusive end-of-day for date-only tx
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end

def _prev_month(year: int, month: int) -> Tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1

def format_period_label(year: int, month: int) -> str:
    # "JAN 25"
    return f"{calendar.month_abbr[month].upper()} {str(year)[-2:]}"

def format_generated_on(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now()).strftime("%d %b %y")

def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


# =============================================================================
# Input parsing (month OR date range)
# =============================================================================

MIN_YEAR = 2020
MAX_YEAR = 2100

def _normalize_user_input(raw: str) -> str:
    s = (raw or "").strip()
    # allow calling with "/exportpdf ..." passed from bot
    s = re.sub(r"^\s*/exportpdf\b", "", s, flags=re.IGNORECASE).strip()
    return s

def parse_month_input(month_input: str) -> Tuple[int, int]:
    """
    Supported:
      - "2026-01" / "2026/01"
      - "01-2026" / "01/2026"
      - "januari 2026" / "jan 2026" / "Jan 2026"
    """
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
    """
    Detect and parse date range in input.
    Supported tokens:
      - 2026-01-12 - 2026-01-20
      - 12-01-2026 - 20-01-2026   (client example)
      - 12/01/2026 - 20/01/2026
    """
    s = (text or "").strip()
    # Extract date-like tokens
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
    # inclusive full day end
    end = datetime(dt2.year, dt2.month, dt2.day, 23, 59, 59)

    if end < start:
        start, end = end, start

    # sanity check
    if start.year < MIN_YEAR or end.year > MAX_YEAR:
        raise PDFInputError(f"Tahun harus dalam range {MIN_YEAR}-{MAX_YEAR}.")

    return start, end


# =============================================================================
# Data normalization + business rules
# =============================================================================

def _get_all_data_safe() -> List[Dict]:
    """Call get_all_data with backward-compatible signature."""
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

    # Your known wallets mapping
    if dompet == "TX SBY(216)":
        return "Texturin Surabaya"
    if dompet == "TX BALI(087)":
        return "Texturin Bali"

    # CV HB - infer from project prefix
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
        # Default Hollawall if unknown prefix (as in your previous logic)
        return "Hollawall"

    return None

def _summarize_period(period_txs: List[Dict]) -> Dict:
    """
    IMPORTANT FIX (vs your v2):
    - office_expense is INCLUDED in expense_total and profit
    """
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
    """
    Returns (text, color) with UX-friendly meaning.
    For expense: lower is better.
    """
    pct = _pct_change(curr, prev)
    if pct is None:
        return ("New", THEME["teal"])
    if abs(pct) < 0.5:
        return ("0%", THEME["muted"])
    sign = "+" if pct > 0 else "-"
    txt = f"{sign}{abs(pct):.0f}%"
    if label == "expense":
        # expense: down is good
        return (txt, THEME["teal"] if pct < 0 else THEME["pink"])
    # income/profit: up is good
    return (txt, THEME["teal"] if pct > 0 else THEME["pink"])

def _finished_projects_by_company(period_txs: List[Dict]) -> Dict[str, List[str]]:
    """
    Detect finished projects inside the period.
    Rules:
      - nama_projek contains "(finish)" OR
      - income tx description contains pelunasan keyword
    """
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

        # fallback: pelunasan
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
            # DP breakdown
            if "dp2" in desc or "dp 2" in desc:
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
    margin_pct = int(round((profit / total_income) * 100)) if total_income else 0

    return {
        "total_income": total_income,
        "dp": dp,
        "dp2": dp2,
        "pelunasan": pelunasan,
        "total_expense": total_expense,
        "total_salary": total_salary,
        "profit": profit,
        "margin_pct": margin_pct,
    }

def _project_timeline(project_txs: List[Dict]) -> Dict:
    if not project_txs:
        return {"start": None, "finish": None}

    dts = [t["dt"] for t in project_txs if isinstance(t.get("dt"), datetime)]
    if not dts:
        return {"start": None, "finish": None}

    start = min(dts)
    # finish: prefer tx with finish marker or pelunasan income
    finish_candidates: List[datetime] = []
    for t in project_txs:
        dt = t.get("dt")
        if not isinstance(dt, datetime):
            continue
        proj = (t.get("nama_projek") or "")
        desc = (t.get("keterangan") or "").lower()
        if _has_finish_marker(proj):
            finish_candidates.append(dt)
        elif _is_income(t) and any(k in desc for k in PELUNASAN_KEYWORDS):
            finish_candidates.append(dt)

    finish = max(finish_candidates) if finish_candidates else max(dts)
    return {"start": start, "finish": finish}

def _largest_expense(project_txs: List[Dict]) -> Optional[Dict]:
    expenses = [t for t in project_txs if _is_expense(t) and not _is_salary(t)]
    if not expenses:
        expenses = [t for t in project_txs if _is_expense(t)]
    if not expenses:
        return None
    return max(expenses, key=lambda x: int(x.get("jumlah", 0) or 0))


# =============================================================================
# Context builder
# =============================================================================

def _build_context_monthly(year: int, month: int) -> Dict:
    all_txs = _get_all_transactions()
    start_dt, end_dt = _month_start_end(year, month)
    period_txs = _filter_period(all_txs, start_dt, end_dt)

    if not period_txs:
        raise PDFNoDataError(format_period_label(year, month))

    prev_year, prev_month = _prev_month(year, month)
    prev_start, prev_end = _month_start_end(prev_year, prev_month)
    prev_txs = _filter_period(all_txs, prev_start, prev_end)

    summary = _summarize_period(period_txs)
    prev_summary = _summarize_period(prev_txs)

    # Group tx by company (exclude office)
    company_period = {c: [] for c in COMPANY_KEYS}
    company_prev = {c: [] for c in COMPANY_KEYS}

    for tx in period_txs:
        comp = _company_from_tx(tx)
        if comp in company_period:
            company_period[comp].append(tx)

    for tx in prev_txs:
        comp = _company_from_tx(tx)
        if comp in company_prev:
            company_prev[comp].append(tx)

    # Income share
    income_by_company = {
        c: sum(int(t.get("jumlah", 0) or 0) for t in company_period[c] if _is_income(t))
        for c in COMPANY_KEYS
    }
    total_income = sum(income_by_company.values())
    income_share = {
        c: (income_by_company[c] / total_income * 100.0) if total_income > 0 else 0.0
        for c in COMPANY_KEYS
    }

    finished_projects = _finished_projects_by_company(period_txs)

    # Project index across all time (for finished project card metrics)
    projects_all: Dict[str, List[Dict]] = {}
    for tx in all_txs:
        if tx.get("company_sheet") == OFFICE_SHEET_NAME:
            continue
        proj_raw = (tx.get("nama_projek") or "").strip()
        if not proj_raw:
            continue
        proj_key = _project_key(proj_raw)
        if not proj_key or proj_key.lower() in PROJECT_EXCLUDE_NAMES:
            continue
        projects_all.setdefault(proj_key, []).append(tx)

    company_details: Dict[str, Dict] = {}
    for comp in COMPANY_KEYS:
        period_list = company_period[comp]
        prev_list = company_prev[comp]

        comp_summary = _summarize_company(period_list)
        comp_prev = _summarize_company(prev_list)

        income_txs = sorted([t for t in period_list if _is_income(t)], key=lambda x: int(x["jumlah"]), reverse=True)
        expense_txs = sorted([t for t in period_list if _is_expense(t) and not _is_salary(t)], key=lambda x: int(x["jumlah"]), reverse=True)
        salary_txs = sorted([t for t in period_list if _is_salary(t)], key=lambda x: int(x["jumlah"]), reverse=True)

        # Build finished project cards (sorted by profit)
        finished_cards = []
        for proj_key in finished_projects.get(comp, []):
            proj_txs = projects_all.get(proj_key, [])
            metrics = _project_metrics(proj_txs)
            timeline = _project_timeline(proj_txs)
            max_exp = _largest_expense(proj_txs)

            finished_cards.append({
                "key": proj_key,
                "name": _project_display_name(proj_key) or proj_key,
                "metrics": metrics,
                "timeline": timeline,
                "max_expense": max_exp,
            })

        finished_cards.sort(key=lambda x: int(x["metrics"]["profit"]), reverse=True)

        company_details[comp] = {
            "summary": comp_summary,
            "prev_summary": comp_prev,
            "income_txs": income_txs,
            "expense_txs": expense_txs,
            "salary_txs": salary_txs,
            "finished_cards": finished_cards,
            "income_amount": income_by_company[comp],
            "income_share": income_share[comp],
        }

    return {
        "mode": "monthly",
        "year": year,
        "month": month,
        "period_label": format_period_label(year, month),
        "generated_on": format_generated_on(),
        "summary": summary,
        "prev_summary": prev_summary,
        "income_share": income_share,
        "income_by_company": income_by_company,
        "finished_projects": finished_projects,
        "company_details": company_details,
    }

def _build_context_range(start_dt: datetime, end_dt: datetime) -> Dict:
    all_txs = _get_all_transactions()
    period_txs = _filter_period(all_txs, start_dt, end_dt)

    period_label = f"{start_dt.strftime('%d-%m-%y')} s/d {end_dt.strftime('%d-%m-%y')}"
    if not period_txs:
        raise PDFNoDataError(period_label)

    summary = _summarize_period(period_txs)

    company_period = {c: [] for c in COMPANY_KEYS}
    for tx in period_txs:
        comp = _company_from_tx(tx)
        if comp in company_period:
            company_period[comp].append(tx)

    income_by_company = {
        c: sum(int(t.get("jumlah", 0) or 0) for t in company_period[c] if _is_income(t))
        for c in COMPANY_KEYS
    }
    total_income = sum(income_by_company.values())
    income_share = {c: (income_by_company[c] / total_income * 100.0) if total_income > 0 else 0.0 for c in COMPANY_KEYS}

    finished_projects = _finished_projects_by_company(period_txs)

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
# Drawing primitives (premium UI toolkit)
# =============================================================================

@dataclass
class UI:
    fonts: Dict[str, str]
    margin: float = 36          # Increased margin for breathing room
    radius: float = 16          # Rounder corners for modern look
    shadow_dx: float = 0        # Centered shadow
    shadow_dy: float = -4       # Shadow below card
    shadow_alpha: float = 0.06  # Subtler primary shadow

def _set_alpha(c: canvas.Canvas, fill: Optional[float] = None, stroke: Optional[float] = None):
    # Some ReportLab builds have alpha, some don't.
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
    Draw a professional card with layered shadow effect.
    
    Args:
        accent_top: Optional tuple (color, height) to draw a top accent bar
    """
    if fill is None:
        fill = THEME["card"]
    
    if shadow:
        # Layer 1: Large, softer shadow (ambient)
        c.saveState()
        _set_alpha(c, fill=0.03, stroke=0)
        c.setFillColor(THEME["shadow"])
        c.roundRect(x - 2, y - 8, w + 4, h + 4, ui.radius + 4, stroke=0, fill=1)
        c.restoreState()
        
        # Layer 2: Medium shadow
        c.saveState()
        _set_alpha(c, fill=0.05, stroke=0)
        c.setFillColor(THEME["shadow"])
        c.roundRect(x, y - 4, w, h + 1, ui.radius + 2, stroke=0, fill=1)
        c.restoreState()
        
        # Layer 3: Tight shadow (depth)
        c.saveState()
        _set_alpha(c, fill=ui.shadow_alpha, stroke=0)
        c.setFillColor(THEME["shadow"])
        c.roundRect(x + 1, y - 2, w - 2, h, ui.radius, stroke=0, fill=1)
        c.restoreState()

    # Main card
    c.saveState()
    c.setFillColor(fill)
    if stroke:
        c.setStrokeColor(stroke)
        c.setLineWidth(1)
        c.roundRect(x, y, w, h, ui.radius, stroke=1, fill=1)
    else:
        # No border - cleaner look
        c.roundRect(x, y, w, h, ui.radius, stroke=0, fill=1)
    c.restoreState()
    
    # Optional top accent bar
    if accent_top:
        accent_color, accent_h = accent_top
        c.saveState()
        c.setFillColor(accent_color)
        # Draw rounded top portion
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
    t = text or ""
    if stringWidth(t, font_name, font_size) <= max_w:
        return t
    ell = "..."
    if stringWidth(ell, font_name, font_size) > max_w:
        return ""
    # binary shrink
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
    """
    Simple word-wrap with ellipsis on last line.
    Handles very long tokens by force-clamping with ellipsis.
    """
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
        # handle super-long single word
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

    # ellipsis on last line if more words remain
    if len(lines) == max_lines:
        joined = " ".join(lines)
        if joined != t:
            lines[-1] = _fit_ellipsis(lines[-1], font_name, font_size, max_w)

    return lines

def _draw_text(c: canvas.Canvas, font: str, size: float, color, x: float, y: float, text: str, align: str = "left"):
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "right":
        c.drawRightString(x, y, text)
    elif align == "center":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)

def _fit_font_size(text: str, font: str, max_size: float, min_size: float, max_w: float) -> float:
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_w:
        size -= 0.5
    return size

def _draw_text_fit(c: canvas.Canvas, font: str, max_size: float, min_size: float, color, x: float, y: float, text: str, max_w: float, align: str = "left"):
    size = _fit_font_size(text, font, max_size, min_size, max_w)
    _draw_text(c, font, size, color, x, y, text, align=align)

def _draw_footer(c: canvas.Canvas, ui: UI, page_w: float):
    y = 14
    _draw_text(c, ui.fonts["regular"], 8.5, THEME["muted2"], ui.margin, y, "Finance Bot • Confidential")
    _draw_text(c, ui.fonts["regular"], 8.5, THEME["muted2"], page_w - ui.margin, y, f"Page {c.getPageNumber()}", align="right")


# =============================================================================
# Components
# =============================================================================

def _draw_header_monthly(c: canvas.Canvas, ui: UI, ctx: Dict, page_w: float, page_h: float, logo_path: Optional[str]):
    header_h = 190
    left_w = 427

    # Header background
    c.saveState()
    c.setFillColor(THEME["teal"])
    c.rect(0, page_h - header_h, left_w, header_h, fill=1, stroke=0)

    # subtle geometric accents (premium feel)
    _set_alpha(c, fill=0.10)
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

    # Texts
    _draw_text(c, ui.fonts["italic"], 10, THEME["white"], 140, page_h - 32, f"Generated on {ctx['generated_on']}")
    _draw_text(c, ui.fonts["bold"], 30, THEME["white"], 140, page_h - 72, "Financial")
    _draw_text(c, ui.fonts["bold"], 30, THEME["white"], 140, page_h - 110, "Report")

    # Period label (right)
    month_part, year_part = ctx["period_label"].split()
    _draw_text(c, ui.fonts["bold"], 34, THEME["teal"], left_w + 18, page_h - 72, month_part)
    _draw_text(c, ui.fonts["bold"], 34, THEME["teal"], left_w + 18, page_h - 110, year_part)

def _draw_header_range(c: canvas.Canvas, ui: UI, ctx: Dict, page_w: float, page_h: float, logo_path: Optional[str]):
    header_h = 190
    left_w = 427

    c.saveState()
    c.setFillColor(THEME["teal"])
    c.rect(0, page_h - header_h, left_w, header_h, fill=1, stroke=0)

    _set_alpha(c, fill=0.10)
    c.setFillColor(colors.white)
    c.circle(left_w - 60, page_h - 40, 36, stroke=0, fill=1)
    c.circle(left_w - 120, page_h - 90, 22, stroke=0, fill=1)
    c.restoreState()

    if logo_path and os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, 30, page_h - 78, width=120, height=40, mask="auto")
        except Exception:
            pass

    _draw_text(c, ui.fonts["italic"], 10, THEME["white"], 140, page_h - 32, f"Generated on {ctx['generated_on']}")
    _draw_text(c, ui.fonts["bold"], 30, THEME["white"], 140, page_h - 72, "Financial")
    _draw_text(c, ui.fonts["bold"], 30, THEME["white"], 140, page_h - 110, "Report")

    # Range info
    start_text = ctx["start_dt"].strftime("%d-%m-%y")
    end_text = ctx["end_dt"].strftime("%d-%m-%y")

    _draw_text(c, ui.fonts["bold"], 20, THEME["teal"], left_w + 18, page_h - 66, "Periodical Audit")
    _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], left_w + 18, page_h - 86, "Dalam rentang waktu")
    _draw_text(c, ui.fonts["regular"], 10, THEME["text"], left_w + 18, page_h - 106, f"{start_text} (00:00)")
    _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], left_w + 18, page_h - 122, "hingga")
    _draw_text(c, ui.fonts["regular"], 10, THEME["text"], left_w + 18, page_h - 138, f"{end_text} (00:00)")

def _draw_kpi_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float,
                   label: str, amount: int, accent, subnote: Optional[str] = None):
    """
    Professional KPI card with top accent bar.
    Clean typography hierarchy and subtle styling.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)

    # Top accent bar - cleaner than left side bar
    accent_h = 4
    c.saveState()
    c.setFillColor(accent)
    # Draw rounded top bar
    c.roundRect(x, y + h - accent_h, w, accent_h, 2, stroke=0, fill=1)
    # Cover bottom corners of accent with card color
    c.setFillColor(THEME["card"])
    c.rect(x, y + h - accent_h, w, 1, stroke=0, fill=1)
    c.restoreState()

    # Label - cleaner styling
    _draw_text(c, ui.fonts["semibold"], 10, THEME["muted"], x + 16, y + h - 24, label.upper())

    # Currency + number - better hierarchy
    num_color = accent if accent != THEME["text"] else THEME["text"]
    # profit negative -> danger
    if label.lower().startswith("profit") and amount < 0:
        num_color = THEME["danger"]
    
    _draw_text(c, ui.fonts["regular"], 11, THEME["muted2"], x + 16, y + h - 48, "Rp")
    amt_text = format_number(amount)
    amt_max_w = w - 54  # from x+38 to right padding
    _draw_text_fit(c, ui.fonts["bold"], 24, 16, num_color, x + 38, y + h - 54, amt_text, amt_max_w, align="left")

    # Subnote - if provided
    if subnote:
        lines = _wrap_lines(subnote, ui.fonts["regular"], 9.5, w - 32, max_lines=2)
        yy = y + 14
        for i, line in enumerate(lines):
            _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], x + 16, yy + (i * 12), line)


def _draw_prev_inline(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float,
                      curr: int, prev: int, label_key: str, value_color):
    """
    Small "Bulan lalu" block aligned next to KPI.
    """
    # Title
    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], x, y_top - 14, "Bulan lalu")
    # Value
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x, y_top - 34, format_number(prev))

    # Delta pill
    pill_text, pill_color = _delta_pill(label_key, curr, prev)
    pill_w = max(40, stringWidth(pill_text, ui.fonts["bold"], 9) + 18)
    pill_h = 16
    py = y_top - 58
    c.setFillColor(pill_color)
    c.roundRect(x, py, pill_w, pill_h, 8, stroke=0, fill=1)
    _draw_text(c, ui.fonts["bold"], 9, THEME["white"], x + pill_w / 2, py + 4.2, pill_text, align="center")

def _draw_income_share_chart(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, items: List[Tuple[str, float, int]]):
    """
    Horizontal bars with percent + amount (all content stays inside box).
    """
    title_h = 18
    bar_h = 12
    gap = 14

    _draw_text(c, ui.fonts["bold"], 11, THEME["text"], x, y_top - 2, "Grafik Pemasukkan")
    y = y_top - title_h

    label_w = 90
    value_w = 42
    amount_w = 92
    bar_w = max(60, w - label_w - value_w - amount_w - 12)
    bar_x = x + label_w
    value_x = x + w - 4

    for i, (comp, pct, amt) in enumerate(items):
        yy = y - (i * (bar_h + gap))
        label = COMPANY_DISPLAY_COVER.get(comp, comp)
        _draw_text(c, ui.fonts["semibold"], 9.5, THEME["text"], x, yy + 1, label)

        # Track background
        c.setFillColor(THEME["track"])
        c.roundRect(bar_x, yy, bar_w, bar_h, 6, stroke=0, fill=1)

        # Fill bar with company color
        fill_w = bar_w * (pct / 100.0)
        c.setFillColor(COMPANY_COLOR.get(comp, THEME["accent"]))
        c.roundRect(bar_x, yy, max(4, fill_w), bar_h, 6, stroke=0, fill=1)

        # Percentage - right aligned inside box
        _draw_text(c, ui.fonts["bold"], 9.5, THEME["text"], value_x, yy + 1, f"{pct:.0f}%", align="right")
        # Amount - below percentage
        _draw_text(c, ui.fonts["regular"], 8.5, THEME["muted2"], value_x, yy - 9, f"Rp {format_number(amt)}", align="right")


def _draw_finished_projects_cover(c: canvas.Canvas, ui: UI, ctx: Dict,
                                 page_w: float, y_top: float, title: str, note: str):
    """
    Cover section:
    - Title + note (stacked, no overlap)
    - 4 columns: per-company finished list (full width)
    - Chart below columns (full width)
    """
    card_x = ui.margin
    card_w = page_w - ui.margin * 2
    card_h = 320
    y = y_top - card_h

    _draw_card(c, ui, card_x, y, card_w, card_h, shadow=True)

    pad = 16
    accent_size = 14
    c.setFillColor(THEME["accent"])
    c.roundRect(card_x + pad, y + card_h - pad - accent_size, accent_size, accent_size, 4, stroke=0, fill=1)
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], card_x + pad + accent_size + 10, y + card_h - pad - 2, title)

    # Note (stacked under title, full width)
    note_lines = _wrap_lines(note, ui.fonts["regular"], 9.5, card_w - 2 * pad, max_lines=2)
    note_y = y + card_h - pad - 20
    for i, line in enumerate(note_lines):
        _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], card_x + pad, note_y - (i * 12), line)

    # Reserve chart area at bottom
    chart_h = 88
    chart_y0 = y + pad
    chart_top = chart_y0 + chart_h

    # Divider above chart
    c.setStrokeColor(THEME["border"])
    c.setLineWidth(1)
    c.line(card_x + pad, chart_top + 6, card_x + card_w - pad, chart_top + 6)

    # Columns area (full width)
    body_top = note_y - (len(note_lines) * 12) - 10
    body_bottom = chart_top + 12
    col_w = (card_w - 2 * pad) / 4.0
    col_x0 = card_x + pad
    col_y0 = body_top - 6

    for idx, comp in enumerate(COMPANY_KEYS):
        cx = col_x0 + idx * col_w

        if idx > 0:
            c.setStrokeColor(THEME["border"])
            c.setLineWidth(1)
            c.line(cx, body_bottom, cx, body_top)

        _draw_text(c, ui.fonts["semibold"], 10.5, THEME["text"], cx + 8, col_y0, COMPANY_DISPLAY_COVER.get(comp, comp))
        count = len(ctx["finished_projects"].get(comp, []))
        _draw_text(c, ui.fonts["bold"], 22, COMPANY_COLOR.get(comp, THEME["accent"]), cx + 8, col_y0 - 24, str(count))

        projects = ctx["finished_projects"].get(comp, []) or []
        display = [_project_display_name(p) or p for p in projects]

        yy = col_y0 - 46
        line_h = 11
        if not display:
            _draw_text(c, ui.fonts["regular"], 9, THEME["muted2"], cx + 8, yy, "Tidak ada project")
        else:
            drawn = 0
            for name in display:
                lines = _wrap_lines(name, ui.fonts["regular"], 9, col_w - 16, max_lines=2)
                if not lines:
                    lines = ["-"]
                needed_h = len(lines) * line_h + 4
                if yy - needed_h < body_bottom:
                    break
                _draw_text(c, ui.fonts["regular"], 9, THEME["text"], cx + 8, yy, f"• {lines[0]}")
                if len(lines) > 1:
                    _draw_text(c, ui.fonts["regular"], 9, THEME["text"], cx + 18, yy - line_h, lines[1])
                    yy -= (line_h * 2)
                else:
                    yy -= line_h
                yy -= 4
                drawn += 1

            remaining = len(display) - drawn
            if remaining > 0 and yy - 12 > body_bottom:
                _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], cx + 8, yy - 4, f"+{remaining} lainnya")

    chart_items = [(c, ctx["income_share"].get(c, 0.0), ctx.get("income_by_company", {}).get(c, 0)) for c in COMPANY_KEYS]
    _draw_income_share_chart(c, ui, card_x + pad, chart_y0 + chart_h - 6, card_w - 2 * pad, chart_items)



# =============================================================================
# Company page components
# =============================================================================

def _draw_company_header(c: canvas.Canvas, ui: UI, ctx: Dict, company: str, page_w: float, page_h: float, header_h: float = 150):
    color = COMPANY_COLOR.get(company, THEME["teal"])
    c.setFillColor(color)
    c.rect(0, page_h - header_h, page_w, header_h, fill=1, stroke=0)

    # Left: generated on (like client)
    _draw_text(c, ui.fonts["italic"], 10, THEME["white"], ui.margin, page_h - 26, f"Generated on {ctx['generated_on']}")

    # Company title
    _draw_text(c, ui.fonts["bold"], 26, THEME["white"], ui.margin, page_h - 70, COMPANY_DISPLAY.get(company, company))

    # Period label right
    month_part, year_part = ctx["period_label"].split()
    _draw_text(c, ui.fonts["bold"], 22, THEME["white"], page_w - ui.margin, page_h - 56, month_part, align="right")
    _draw_text(c, ui.fonts["bold"], 22, THEME["white"], page_w - ui.margin, page_h - 86, year_part, align="right")

def _draw_two_value_row(c: canvas.Canvas, ui: UI, x: float, y: float, label: str, curr: int, prev: int, key: str):
    """
    Row with:
    label | prev value | current value | delta pill
    """
    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], x, y, label)
    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted2"], x + 120, y, f"Prev: {format_currency(prev)}")
    _draw_text(c, ui.fonts["semibold"], 10.5, THEME["text"], x + 280, y, f"Now: {format_currency(curr)}")

    pill_text, pill_color = _delta_pill(key, curr, prev)
    pw = max(42, stringWidth(pill_text, ui.fonts["bold"], 9) + 18)
    ph = 16
    c.setFillColor(pill_color)
    c.roundRect(x + 460, y - 4, pw, ph, 8, stroke=0, fill=1)
    _draw_text(c, ui.fonts["bold"], 9, THEME["white"], x + 460 + pw / 2, y - 0.2, pill_text, align="center")

def _draw_comparison_chart(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float,
                           curr: Dict, prev: Dict):
    """
    Clean comparison panel (no overflow).
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)

    _draw_text(c, ui.fonts["bold"], 12, THEME["text"], x + 16, y + h - 20, "Perbandingan Bulan Lalu")

    # Column widths
    col_label = 90
    col_prev = 110
    col_now = 110
    col_delta = w - (col_label + col_prev + col_now) - 32
    if col_delta < 70:
        col_prev = 95
        col_now = 95
        col_delta = w - (col_label + col_prev + col_now) - 32

    header_y = y + h - 38
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], x + 16, header_y, "Item")
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], x + 16 + col_label + col_prev - 4, header_y, "Bulan lalu", align="right")
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], x + 16 + col_label + col_prev + col_now - 4, header_y, "Bulan ini", align="right")
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], x + 16 + col_label + col_prev + col_now + col_delta - 4, header_y, "Selisih", align="right")

    rows = [
        ("Omset", "income_total", THEME["accent"], "income"),
        ("Pengeluaran", "expense_total", THEME["warning"], "expense"),
        ("Profit", "profit", THEME["success"], "profit"),
    ]

    row_h = 26
    start_y = header_y - 16
    for idx, (label, key, color_now, delta_key) in enumerate(rows):
        cy = start_y - idx * row_h
        curr_val = int(curr.get(key, 0) or 0)
        prev_val = int(prev.get(key, 0) or 0)

        _draw_text(c, ui.fonts["semibold"], 9.5, THEME["text"], x + 16, cy, label)

        _draw_text_fit(c, ui.fonts["regular"], 9.5, 8, THEME["muted"], x + 16 + col_label + col_prev - 4, cy, format_currency(prev_val), col_prev - 6, align="right")
        _draw_text_fit(c, ui.fonts["semibold"], 9.5, 8, THEME["text"], x + 16 + col_label + col_prev + col_now - 4, cy, format_currency(curr_val), col_now - 6, align="right")

        pill_text, pill_color = _delta_pill(delta_key, curr_val, prev_val)
        pw = max(42, stringWidth(pill_text, ui.fonts["bold"], 8.5) + 16)
        ph = 16
        px = x + 16 + col_label + col_prev + col_now + col_delta - pw - 4
        c.setFillColor(pill_color)
        c.roundRect(px, cy - 6, pw, ph, 8, stroke=0, fill=1)
        _draw_text(c, ui.fonts["bold"], 8.5, THEME["white"], px + pw / 2, cy - 2, pill_text, align="center")

        # Row divider
        c.setStrokeColor(THEME["border"])
        c.setLineWidth(0.6)
        c.line(x + 16, cy - 10, x + w - 16, cy - 10)
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
    h: float = 190,
):
    """
    Professional transaction list card.
    Features: Top accent bar, clean typography, subtle dividers.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    
    # Title with better styling
    _draw_text(c, ui.fonts["bold"], 12, THEME["text"], x + 16, y + h - 22, title)

    # Top accent bar - subtle horizontal line under title
    c.saveState()
    c.setFillColor(kind_color)
    c.roundRect(x + 16, y + h - 34, 24, 3, 1.5, stroke=0, fill=1)
    c.restoreState()

    if not items:
        _draw_text(c, ui.fonts["regular"], 10, THEME["muted2"], x + 16, y + h - 52, "Tidak ada data")
        return

    font_name = ui.fonts["regular"]
    font_size = 10
    amount_font = ui.fonts["bold"]
    amount_size = 10

    # compute amount column width based on visible items
    sample_limit = max_items or min(len(items), 20)
    sample = items[:sample_limit]
    amount_w = 0
    for tx in sample:
        amt = int(tx.get("jumlah", 0) or 0)
        label = f"Rp {format_number(amt)}"
        amount_w = max(amount_w, stringWidth(label, amount_font, amount_size))
    amount_w = max(amount_w, 65)

    padding_x = 16
    desc_max_w = max(40, w - padding_x * 2 - amount_w - 12)

    yy = y + h - 52
    drawn = 0
    for i, tx in enumerate(sample, start=1):
        desc = (tx.get("keterangan") or "").strip() or "-"
        prefix = f"{i}."
        prefix_w = stringWidth(prefix + " ", font_name, font_size)
        wrapped = _wrap_lines(desc, font_name, font_size, max(30, desc_max_w - prefix_w), max_lines=2)
        if not wrapped:
            wrapped = ["-"]

        line_h = 14
        row_h = line_h * len(wrapped) + 10
        line_y = yy - row_h

        if line_y < y + 14:
            break

        # line 1
        _draw_text(c, font_name, font_size, THEME["text"], x + padding_x, line_y + row_h - 18, f"{prefix} {wrapped[0]}")
        # line 2 (if any)
        if len(wrapped) > 1:
            _draw_text(c, font_name, font_size, THEME["muted"], x + padding_x + prefix_w, line_y + row_h - 32, wrapped[1])

        # amount aligned right (on first line)
        amt = int(tx.get("jumlah", 0) or 0)
        _draw_text(c, amount_font, amount_size, THEME["text"], x + w - padding_x, line_y + row_h - 18, f"Rp {format_number(amt)}", align="right")

        drawn += 1
        yy = line_y

        # divider - subtle
        if i < len(sample):
            c.saveState()
            c.setStrokeColor(THEME["border"])
            c.setLineWidth(0.5)
            c.line(x + padding_x, yy + 5, x + w - padding_x, yy + 5)
            c.restoreState()

    remaining = len(items) - drawn
    if remaining > 0 and yy - 18 > y + 12:
        _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], x + padding_x, yy - 10, f"+{remaining} lainnya")


def _draw_insight_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, company_details: Dict, h: float = 170):
    """
    Professional insight card with clean typography.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    
    # Title with accent line
    _draw_text(c, ui.fonts["bold"], 12, THEME["text"], x + 16, y + h - 22, "Insight")
    c.saveState()
    c.setFillColor(THEME["accent"])
    c.roundRect(x + 16, y + h - 34, 20, 3, 1.5, stroke=0, fill=1)
    c.restoreState()

    lines: List[str] = []
    exp = company_details.get("expense_txs") or []
    sal = company_details.get("salary_txs") or []

    if exp:
        top = exp[0]
        lines.append(f"Pengeluaran terbesar bulan ini: {_fit_ellipsis(top.get('keterangan',''), ui.fonts['regular'], 10, w-220)} (Rp {format_number(int(top.get('jumlah',0) or 0))})")
    else:
        lines.append("Pengeluaran terbesar bulan ini: Tidak ada data")

    if sal:
        smax = sal[0]
        smin = sal[-1] if len(sal) > 1 else sal[0]
        lines.append(f"Gaji terbesar: {_fit_ellipsis(smax.get('keterangan',''), ui.fonts['regular'], 10, w-190)} (Rp {format_number(int(smax.get('jumlah',0) or 0))})")
        lines.append(f"Gaji terkecil: {_fit_ellipsis(smin.get('keterangan',''), ui.fonts['regular'], 10, w-190)} (Rp {format_number(int(smin.get('jumlah',0) or 0))})")
    else:
        lines.append("Gaji terbesar: Tidak ada data")
        lines.append("Gaji terkecil: Tidak ada data")

    # best/worst finished project of this month (by profit)
    cards = company_details.get("finished_cards") or []
    if cards:
        best = max(cards, key=lambda x: int(x["metrics"]["profit"]))
        worst = min(cards, key=lambda x: int(x["metrics"]["profit"]))
        lines.append(f"Finished project terbaik: {_fit_ellipsis(best['name'], ui.fonts['regular'], 10, w-220)} (Rp {format_number(int(best['metrics']['profit']))})")
        lines.append(f"Finished project terendah: {_fit_ellipsis(worst['name'], ui.fonts['regular'], 10, w-220)} (Rp {format_number(int(worst['metrics']['profit']))})")
    else:
        lines.append("Finished project terbaik: Tidak ada data")
        lines.append("Finished project terendah: Tidak ada data")

    # draw lines with better spacing
    yy = y + h - 50
    max_lines = 5 if h >= 170 else 4
    for i, line in enumerate(lines[:max_lines], start=0):
        _draw_text(c, ui.fonts["regular"], 10, THEME["text"], x + 16, yy - i * 22, _fit_ellipsis(line, ui.fonts["regular"], 10, w - 32))


def _draw_project_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float,
                       idx: int, company: str, proj: Dict):
    """
    Professional project card with top accent bar.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)

    accent = COMPANY_COLOR.get(company, THEME["accent"])
    
    # Top accent bar - cleaner than side bar
    accent_h = 4
    c.saveState()
    c.setFillColor(accent)
    c.roundRect(x, y + h - accent_h, w, accent_h + 2, 2, stroke=0, fill=1)
    c.setFillColor(THEME["card"])
    c.rect(x, y + h - accent_h, w, 1, stroke=0, fill=1)
    c.restoreState()

    name = proj.get("name", "Project")
    name = _fit_ellipsis(f"{idx}. {name}", ui.fonts["bold"], 13, w - 190)
    _draw_text(c, ui.fonts["bold"], 13, THEME["text"], x + 18, y + h - 26, name)

    metrics = proj.get("metrics", {}) or {}
    profit = int(metrics.get("profit", 0) or 0)
    margin = int(metrics.get("margin_pct", 0) or 0)

    profit_color = THEME["success"] if profit >= 0 else THEME["danger"]
    _draw_text(c, ui.fonts["semibold"], 10, THEME["muted"], x + w - 18, y + h - 24, "Profit Kotor", align="right")
    profit_text = f"Rp {format_number(profit)}  ({margin}%)"
    _draw_text_fit(
        c,
        ui.fonts["bold"],
        13,
        9,
        profit_color,
        x + w - 18,
        y + h - 42,
        profit_text,
        180,
        align="right",
    )

    timeline = proj.get("timeline", {}) or {}
    start_dt = timeline.get("start")
    finish_dt = timeline.get("finish")
    start_txt = start_dt.strftime("%d %b %Y") if isinstance(start_dt, datetime) else "-"
    finish_txt = finish_dt.strftime("%d %b %Y") if isinstance(finish_dt, datetime) else "-"

    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], x + 18, y + h - 46, f"Mulai: {start_txt}")
    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], x + 18, y + h - 60, f"Selesai: {finish_txt}")

    # Metrics grid
    # Row 1: Nilai, DP, DP2, Pelunasan
    # Row 2: Pengeluaran, Gaji, Pengeluaran terbesar
    col1_x = x + 18
    col_w = (w - 36) / 4.0

    def metric_cell(ix: int, label: str, value: int, y0: float):
        cx = col1_x + ix * col_w
        _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], cx, y0, label)
        val_text = f"Rp {format_number(value)}"
        _draw_text_fit(
            c,
            ui.fonts["bold"],
            11,
            8.5,
            THEME["text"],
            cx + col_w - 2,
            y0 - 15,
            val_text,
            col_w - 6,
            align="right",
        )

    y_row1 = y + 58
    metric_cell(0, "Nilai", int(metrics.get("total_income", 0) or 0), y_row1)
    metric_cell(1, "DP", int(metrics.get("dp", 0) or 0), y_row1)
    metric_cell(2, "DP 2", int(metrics.get("dp2", 0) or 0), y_row1)
    metric_cell(3, "Pelunasan", int(metrics.get("pelunasan", 0) or 0), y_row1)

    y_row2 = y + 30
    metric_cell(0, "Pengeluaran", int(metrics.get("total_expense", 0) or 0), y_row2)
    metric_cell(1, "Gaji", int(metrics.get("total_salary", 0) or 0), y_row2)

    max_exp = proj.get("max_expense")
    if max_exp:
        desc = _fit_ellipsis(max_exp.get("keterangan", ""), ui.fonts["regular"], 9, col_w * 2 - 12)
        amt = int(max_exp.get("jumlah", 0) or 0)
        cx = col1_x + 2 * col_w
        _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], cx, y_row2, "Pengeluaran Terbesar")
        _draw_text(c, ui.fonts["regular"], 9, THEME["text"], cx, y_row2 - 13, desc)
        _draw_text(c, ui.fonts["bold"], 11, THEME["text"], cx + col_w * 2 - 8, y_row2 - 15, f"Rp {format_number(amt)}", align="right")
    else:
        cx = col1_x + 2 * col_w
        _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], cx, y_row2, "Pengeluaran Terbesar")
        _draw_text(c, ui.fonts["regular"], 9, THEME["muted2"], cx, y_row2 - 15, "-")

    # divider line - subtle
    c.saveState()
    c.setStrokeColor(THEME["border"])
    c.setLineWidth(0.5)
    c.line(x + 18, y + h - 72, x + w - 18, y + h - 72)
    c.restoreState()



# =============================================================================
# Pages
# =============================================================================

def draw_cover_monthly(c: canvas.Canvas, ui: UI, ctx: Dict, logo_path: Optional[str] = None):
    page_w, page_h = A4
    # background
    c.setFillColor(THEME["bg"])
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    _draw_header_monthly(c, ui, ctx, page_w, page_h, logo_path=logo_path)

    summary = ctx["summary"]
    prev = ctx["prev_summary"]

    # KPI stack
    kpi_x = ui.margin
    kpi_w = 270
    kpi_h = 86
    gap = 14
    y_top = page_h - 214  # below header, safe spacing

    _draw_kpi_card(c, ui, kpi_x, y_top, kpi_w, kpi_h, "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(
        c, ui, kpi_x, y_top - (kpi_h + gap), kpi_w, kpi_h,
        "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"],
        subnote=f"(Pengeluaran Kantor Rp {format_number(int(summary['office_expense']))})"
    )
    _draw_kpi_card(c, ui, kpi_x, y_top - 2 * (kpi_h + gap), kpi_w, kpi_h, "Profit", int(summary["profit"]), THEME["teal"])

    # Divider + prev inline
    divider_x = kpi_x + kpi_w + 18
    c.setStrokeColor(THEME["border"])
    c.setLineWidth(2)
    c.line(divider_x, y_top - 6, divider_x, y_top - 2 * (kpi_h + gap) - kpi_h + 6)

    prev_x = divider_x + 18
    _draw_prev_inline(c, ui, prev_x, y_top, 200, int(summary["income_total"]), int(prev["income_total"]), "income", THEME["text"])
    _draw_prev_inline(c, ui, prev_x, y_top - (kpi_h + gap), 200, int(summary["expense_total"]), int(prev["expense_total"]), "expense", THEME["pink"])
    _draw_prev_inline(c, ui, prev_x, y_top - 2 * (kpi_h + gap), 200, int(summary["profit"]), int(prev["profit"]), "profit", THEME["teal"])

    # Finished projects section card
    _draw_finished_projects_cover(
        c, ui, ctx, page_w,
        y_top=page_h - 510,
        title="Project yang Selesai Bulan ini",
        note="Adalah Project, yang telah tuntas pada bulan ini. Untuk mulainya tidak harus bulan ini."
    )

    _draw_footer(c, ui, page_w)

def draw_cover_periodical(c: canvas.Canvas, ui: UI, ctx: Dict, logo_path: Optional[str] = None):
    page_w, page_h = A4
    c.setFillColor(THEME["bg"])
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    _draw_header_range(c, ui, ctx, page_w, page_h, logo_path=logo_path)

    summary = ctx["summary"]
    # KPI stack (no "bulan lalu")
    kpi_x = ui.margin
    kpi_w = 270
    kpi_h = 86
    gap = 14
    y_top = page_h - 214

    _draw_kpi_card(c, ui, kpi_x, y_top, kpi_w, kpi_h, "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(
        c, ui, kpi_x, y_top - (kpi_h + gap), kpi_w, kpi_h,
        "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"],
        subnote=f"(Pengeluaran Kantor Rp {format_number(int(summary['office_expense']))})"
    )
    _draw_kpi_card(c, ui, kpi_x, y_top - 2 * (kpi_h + gap), kpi_w, kpi_h, "Profit", int(summary["profit"]), THEME["teal"])

    # Finished projects section
    _draw_finished_projects_cover(
        c, ui, ctx, page_w,
        y_top=page_h - 510,
        title="Project Selesai",
        note="Adalah Project, yang telah tuntas pada periode ini."
    )

    _draw_footer(c, ui, page_w)

def _estimate_company_page_height(ui: UI, details: Dict, base_h: float = 1621) -> float:
    """
    Estimate required page height so finished project cards never overflow.
    Keeps top layout identical; only extends page downward if needed.
    """
    header_h = 150
    top_gap = 24
    kpi_h = 92
    kpi_gap = 18
    row_h = 132
    row_gap = 18
    list_h = 190
    list_gap = 16
    list2_gap = 22
    title_gap = 32
    footer_space = 26

    fixed = (
        header_h + top_gap +
        kpi_h + kpi_gap +
        row_h + row_gap +
        list_h + list_gap +
        list_h + list2_gap +
        title_gap +
        ui.margin + footer_space
    )

    cards = details.get("finished_cards") or []
    if not cards:
        return base_h

    card_h = 118
    card_gap = 12
    card_space = len(cards) * (card_h + card_gap) - card_gap

    needed = fixed + card_space
    return float(max(base_h, needed))


def draw_company_page(c: canvas.Canvas, ui: UI, ctx: Dict, company: str, page_h: Optional[float] = None):
    page_w = A4[0]
    page_h = page_h or 1621  # default tall page
    c.setFillColor(THEME["bg"])
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    _draw_company_header(c, ui, ctx, company, page_w, page_h, header_h=150)

    details = ctx["company_details"][company]
    summary = details["summary"]
    prev = details["prev_summary"]

    content_x = ui.margin
    content_w = page_w - 2 * ui.margin

    # KPI row (3 cards)
    y = page_h - 150 - 24
    kpi_h = 92
    gap = 14
    kpi_w = (content_w - 2 * gap) / 3.0

    _draw_kpi_card(c, ui, content_x + 0 * (kpi_w + gap), y, kpi_w, kpi_h, "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(c, ui, content_x + 1 * (kpi_w + gap), y, kpi_w, kpi_h, "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"])
    _draw_kpi_card(c, ui, content_x + 2 * (kpi_w + gap), y, kpi_w, kpi_h, "Profit", int(summary["profit"]), THEME["teal"])

    y -= (kpi_h + 18)

    # Row: last month summary (left) + comparison chart (right)
    left_w = 240
    row_h = 132

    _draw_card(c, ui, content_x, y - row_h, left_w, row_h, shadow=True)
    _draw_text(c, ui.fonts["bold"], 11, THEME["text"], content_x + 12, y - 18, "Bulan lalu (ringkas)")

    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], content_x + 12, y - 44, "Omset")
    _draw_text(c, ui.fonts["semibold"], 10.5, THEME["text"], content_x + left_w - 12, y - 44, format_currency(int(prev["income_total"])), align="right")

    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], content_x + 12, y - 70, "Pengeluaran")
    _draw_text(c, ui.fonts["semibold"], 10.5, THEME["text"], content_x + left_w - 12, y - 70, format_currency(int(prev["expense_total"])), align="right")

    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], content_x + 12, y - 96, "Profit")
    pcol = THEME["text"] if int(prev["profit"]) >= 0 else THEME["danger"]
    _draw_text(c, ui.fonts["bold"], 10.5, pcol, content_x + left_w - 12, y - 96, format_currency(int(prev["profit"])), align="right")

    chart_x = content_x + left_w + 14
    chart_w = content_w - left_w - 14
    _draw_comparison_chart(c, ui, chart_x, y, chart_w, row_h, summary, prev)

    y -= (row_h + 18)

    # Lists row (2 columns for better readability)
    col_gap = 16
    col_w = (content_w - col_gap) / 2.0
    list_h = 190

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

    y -= (list_h + 16)

    _draw_tx_list_card(
        c, ui, content_x, y, col_w,
        "List Gaji", details["salary_txs"], COMPANY_COLOR.get(company, THEME["teal"]),
        max_items=None, h=list_h
    )
    _draw_insight_card(c, ui, content_x + col_w + col_gap, y, col_w, details, h=list_h)

    y -= (list_h + 22)

    # Finished projects section
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], content_x, y, "Finished Projects")
    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], content_x, y - 16, "Project yang tuntas pada bulan ini (mulai bisa dari bulan lain).")

    y -= 32

    cards = details.get("finished_cards") or []
    if not cards:
        _draw_text(c, ui.fonts["regular"], 10, THEME["muted2"], content_x, y - 10, "Tidak ada project selesai pada bulan ini.")
        _draw_footer(c, ui, page_w)
        return

    card_gap = 12
    card_h = 118
    footer_space = 26
    available_h = y - (ui.margin + footer_space)
    max_cards = max(1, int((available_h + card_gap) // (card_h + card_gap)))

    for i, proj in enumerate(cards[:max_cards], start=1):
        _draw_project_card(c, ui, content_x, y, content_w, card_h, i, company, proj)
        y -= (card_h + card_gap)

    if len(cards) > max_cards:
        _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], content_x, y - 4, f"+{len(cards) - max_cards} project lainnya tidak ditampilkan (untuk menjaga layout tetap rapi).")

    _draw_footer(c, ui, page_w)


# =============================================================================
# PDF generators
# =============================================================================

def generate_pdf_report_v3_monthly(year: int, month: int, output_dir: Optional[str] = None) -> str:
    """
    Monthly export:
      - Cover (A4)
      - Company pages (custom tall pages)
    """
    ctx = _build_context_monthly(year, month)
    fonts = register_fonts()
    ui = UI(fonts=fonts)

    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    fname = _safe_filename(f"Laporan_Keuangan_{ctx['period_label']}") + ".pdf"
    output_path = os.path.join(out_dir, fname)

    logo_path = os.getenv("HOLLAWALL_LOGO_PATH")

    c = canvas.Canvas(output_path, pagesize=A4)
    draw_cover_monthly(c, ui, ctx, logo_path=logo_path)
    c.showPage()

    for comp in COMPANY_KEYS:
        page_h = _estimate_company_page_height(ui, ctx["company_details"][comp], base_h=1621)
        c.setPageSize((A4[0], page_h))
        draw_company_page(c, ui, ctx, comp, page_h=page_h)
        c.showPage()

    c.save()
    secure_log("INFO", f"PDF generated: {output_path}")
    return output_path

def generate_pdf_report_v3_range(start_dt: datetime, end_dt: datetime, output_dir: Optional[str] = None) -> str:
    """
    Periodical Audit export:
      - Cover only (A4)
    """
    ctx = _build_context_range(start_dt, end_dt)
    fonts = register_fonts()
    ui = UI(fonts=fonts)

    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    fname = _safe_filename(f"Laporan_Keuangan_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}") + ".pdf"
    output_path = os.path.join(out_dir, fname)

    logo_path = os.getenv("HOLLAWALL_LOGO_PATH")

    c = canvas.Canvas(output_path, pagesize=A4)
    draw_cover_periodical(c, ui, ctx, logo_path=logo_path)
    c.save()

    secure_log("INFO", f"PDF generated: {output_path}")
    return output_path


# Backward-compatible wrapper (if other modules call this)
def generate_pdf_report(year: int, month: int, output_dir: Optional[str] = None, **kwargs) -> str:
    return generate_pdf_report_v3_monthly(year, month, output_dir=output_dir)


def generate_pdf_from_input(period_input: str, output_dir: Optional[str] = None) -> str:
    """
    Main entry for bot command.
    Accepts:
      - Month input: "2026-01", "januari 2026"
      - Range input: "12-01-2026 - 20-01-2026"
    Raises:
      PDFInputError (format)
      PDFNoDataError (no data)
      PDFReportError (other)
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
        return generate_pdf_report_v3_range(start_dt, end_dt, output_dir=output_dir)

    year, month = parse_month_input(s)
    return generate_pdf_report_v3_monthly(year, month, output_dir=output_dir)


# =============================================================================
# Debug / local run (only for dev, requires your sheets_helper configured)
# =============================================================================

if __name__ == "__main__":
    # quick sanity parse tests (no sheet access needed)
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
