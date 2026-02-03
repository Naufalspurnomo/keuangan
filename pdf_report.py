# -*- coding: utf-8 -*-
"""
Finance Bot PDF Export (FINAL POLISH)

FIXES APPLIED:
1. Income Chart: Increased gap between title and first bar.
2. Comparison Chart: Fixed legend overlap by moving it below the title.
3. Lists/Insights: Increased card height, reduced font size slightly, enabled text wrapping.
4. Finished Projects: Improved vertical rhythm between labels and values.
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
# Errors
# =============================================================================

class PDFReportError(Exception):
    pass

class PDFInputError(PDFReportError):
    pass

class PDFNoDataError(PDFReportError):
    def __init__(self, period_label: str):
        super().__init__(f"Tidak ada data transaksi untuk periode: {period_label}")
        self.period_label = period_label


# =============================================================================
# Theme
# =============================================================================

THEME = {
    "bg": colors.HexColor("#F9FAFB"),
    "card": colors.white,
    "card_alt": colors.HexColor("#FAFBFC"),
    "border": colors.HexColor("#E5E7EB"),
    "border_light": colors.HexColor("#F3F4F6"),
    "divider": colors.HexColor("#E5E7EB"),
    "shadow": colors.HexColor("#111827"),
    "track": colors.HexColor("#F3F4F6"),
    "text": colors.HexColor("#111827"),
    "text_secondary": colors.HexColor("#374151"),
    "muted": colors.HexColor("#6B7280"),
    "muted2": colors.HexColor("#9CA3AF"),
    "accent": colors.HexColor("#0EA5E9"),
    "accent_dark": colors.HexColor("#0284C7"),
    "accent_light": colors.HexColor("#7DD3FC"),
    "success": colors.HexColor("#10B981"),
    "success_light": colors.HexColor("#D1FAE5"),
    "warning": colors.HexColor("#F59E0B"),
    "warning_light": colors.HexColor("#FEF3C7"),
    "danger": colors.HexColor("#EF4444"),
    "danger_light": colors.HexColor("#FEE2E2"),
    "white": colors.white,
    "teal": colors.HexColor("#0EA5E9"),
    "teal2": colors.HexColor("#0284C7"),
    "pink": colors.HexColor("#EF4444"),
    "green": colors.HexColor("#10B981"),
    "chart_prev": colors.HexColor("#E5E7EB"),
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
# Fonts & Assets
# =============================================================================

def _get_logo_path() -> Optional[str]:
    """Resolve logo path from environment variable, relative to script directory."""
    logo_env = os.getenv("HOLLAWALL_LOGO_PATH")
    if not logo_env:
        return None
    
    # If it's already an absolute path, use it directly
    if os.path.isabs(logo_env):
        return logo_env if os.path.exists(logo_env) else None
    
    # Otherwise, resolve relative to script directory
    base_dir = os.path.dirname(__file__)
    full_path = os.path.join(base_dir, logo_env)
    return full_path if os.path.exists(full_path) else None

def register_fonts() -> Dict[str, str]:
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

def format_currency_short(amount: int) -> str:
    abs_amt = abs(amount)
    if abs_amt >= 1_000_000_000:
        val = amount / 1_000_000_000
        return f"{val:.1f}M".replace(".0M", "M")
    if abs_amt >= 1_000_000:
        val = amount / 1_000_000
        return f"{val:.1f}jt".replace(".0jt", "jt")
    if abs_amt >= 1_000:
        val = amount / 1_000
        return f"{val:.0f}rb"
    return str(amount)

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


# =============================================================================
# Input parsing
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
            "januari": 1, "jan": 1, "februari": 2, "feb": 2, "maret": 3, "mar": 3,
            "april": 4, "apr": 4, "mei": 5, "may": 5, "juni": 6, "jun": 6,
            "juli": 7, "jul": 7, "agustus": 8, "aug": 8, "ags": 8,
            "september": 9, "sep": 9, "oktober": 10, "okt": 10, "oct": 10,
            "november": 11, "nov": 11, "desember": 12, "des": 12, "dec": 12,
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
        raise PDFInputError(f"Format periode tidak dikenali: '{month_input}'.")

    if month < 1 or month > 12:
        raise PDFInputError(f"Bulan tidak valid: {month}. Harus 1-12.")
    if year < MIN_YEAR or year > MAX_YEAR:
        raise PDFInputError(f"Tahun tidak valid: {year}. Harus {MIN_YEAR}-{MAX_YEAR}.")

    return year, month

def _parse_any_date_token(token: str) -> Optional[datetime]:
    token = (token or "").strip()
    if not token:
        return None
    fmts = ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"]
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
        raise PDFInputError("Format rentang tanggal tidak valid.")

    start = datetime(dt1.year, dt1.month, dt1.day, 0, 0, 0)
    end = datetime(dt2.year, dt2.month, dt2.day, 23, 59, 59)
    if end < start:
        start, end = end, start
    return start, end


# =============================================================================
# Data normalization
# =============================================================================

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
        if isinstance(dt, datetime) and start_dt <= dt <= end_dt:
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
        return 0.0 if curr == 0 else None
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
        if not proj_key or proj_key.lower() in PROJECT_EXCLUDE_NAMES:
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
        "dp": dp, "dp2": dp2, "pelunasan": pelunasan,
        "total_income": total_income, "total_expense": total_expense,
        "total_salary": total_salary, "profit": profit, "margin_pct": margin_pct,
    }

def _build_context_monthly(year: int, month: int) -> Dict:
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
        income_share[comp] = (income_by_company[comp] / total_income * 100) if total_income > 0 else 0.0
        
    finished_projects = _finished_projects_by_company(period_txs)
    company_details = {}
    for comp in COMPANY_KEYS:
        comp_txs = company_txs_map[comp]
        comp_summary = _summarize_company(comp_txs)
        prev_comp_txs = [t for t in prev_txs if _company_from_tx(t) == comp]
        prev_comp_summary = _summarize_company(prev_comp_txs)
        
        income_txs = sorted([t for t in comp_txs if _is_income(t)], key=lambda x: int(x.get("jumlah", 0) or 0), reverse=True)
        expense_txs = sorted([t for t in comp_txs if _is_expense(t) and not _is_salary(t)], key=lambda x: int(x.get("jumlah", 0) or 0), reverse=True)
        salary_txs = sorted([t for t in comp_txs if _is_salary(t)], key=lambda x: int(x.get("jumlah", 0) or 0), reverse=True)
        
        finished_proj_names = finished_projects.get(comp, [])
        finished_cards = []
        for proj_name in finished_proj_names:
            proj_txs = [t for t in comp_txs if _project_key(t.get("nama_projek", "")) == proj_name]
            if not proj_txs:
                continue
            metrics = _project_metrics(proj_txs)
            dts = [t["dt"] for t in proj_txs if isinstance(t.get("dt"), datetime)]
            timeline = {"start": min(dts) if dts else None, "finish": max(dts) if dts else None}
            proj_expenses = [t for t in proj_txs if _is_expense(t) and not _is_salary(t)]
            max_expense = max(proj_expenses, key=lambda x: int(x.get("jumlah", 0) or 0)) if proj_expenses else None
            finished_cards.append({
                "name": _project_display_name(proj_name),
                "metrics": metrics,
                "timeline": timeline,
                "max_expense": max_expense,
            })
            
        company_details[comp] = {
            "summary": comp_summary, "prev_summary": prev_comp_summary,
            "income_txs": income_txs, "expense_txs": expense_txs, "salary_txs": salary_txs,
            "finished_cards": finished_cards,
        }
        
    return {
        "mode": "monthly", "year": year, "month": month,
        "period_label": period_label, "generated_on": format_generated_on(),
        "summary": summary, "prev_summary": prev_summary,
        "income_share": income_share, "income_by_company": income_by_company,
        "finished_projects": finished_projects, "company_details": company_details,
    }

def _build_context_range(start_dt: datetime, end_dt: datetime) -> Dict:
    all_txs = _get_all_transactions()
    period_txs = _filter_period(all_txs, start_dt, end_dt)
    if not period_txs:
        raise PDFNoDataError(f"{start_dt.date()} - {end_dt.date()}")
    
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
        income_share[comp] = (income_by_company[comp] / total_income * 100) if total_income > 0 else 0.0
        
    finished_projects = _finished_projects_by_company(period_txs)
    period_label = f"{start_dt.strftime('%d %b %y')} - {end_dt.strftime('%d %b %y')}"
    
    return {
        "mode": "range", "generated_on": format_generated_on(),
        "summary": summary, "income_share": income_share,
        "income_by_company": income_by_company, "finished_projects": finished_projects,
        "start_dt": start_dt, "end_dt": end_dt, "period_label": period_label,
    }


# =============================================================================
# Drawing primitives
# =============================================================================

@dataclass
class UI:
    fonts: Dict[str, str]
    margin: float = 40
    radius: float = 18
    shadow_dx: float = 0
    shadow_dy: float = -3
    shadow_alpha: float = 0.05

def _set_alpha(c: canvas.Canvas, fill: Optional[float] = None, stroke: Optional[float] = None):
    if fill is not None and hasattr(c, "setFillAlpha"):
        try: c.setFillAlpha(fill)
        except Exception: pass
    if stroke is not None and hasattr(c, "setStrokeAlpha"):
        try: c.setStrokeAlpha(stroke)
        except Exception: pass

def _draw_card(c: canvas.Canvas, ui: UI, x: float, y: float, w: float, h: float,
               fill=None, stroke=None, shadow: bool = True, accent_top: Optional[tuple] = None):
    if fill is None: fill = THEME["card"]
    if shadow:
        c.saveState()
        _set_alpha(c, fill=0.02, stroke=0)
        c.setFillColor(THEME["shadow"])
        c.roundRect(x - 1, y - 6, w + 2, h + 3, ui.radius + 3, stroke=0, fill=1)
        c.restoreState()
        
        c.saveState()
        _set_alpha(c, fill=0.04, stroke=0)
        c.setFillColor(THEME["shadow"])
        c.roundRect(x, y - 3, w, h + 1, ui.radius + 1, stroke=0, fill=1)
        c.restoreState()
        
        c.saveState()
        _set_alpha(c, fill=ui.shadow_alpha, stroke=0)
        c.setFillColor(THEME["shadow"])
        c.roundRect(x, y - 1, w, h, ui.radius, stroke=0, fill=1)
        c.restoreState()

    c.saveState()
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, ui.radius, stroke=0, fill=1)
    c.restoreState()
    
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
    t = text or ""
    if stringWidth(t, font_name, font_size) <= max_w: return t
    ell = "..."
    if stringWidth(ell, font_name, font_size) > max_w: return ""
    lo, hi = 0, len(t)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = t[:mid].rstrip() + ell
        if stringWidth(cand, font_name, font_size) <= max_w:
            best = cand; lo = mid + 1
        else: hi = mid - 1
    return best or ell

def _wrap_lines(text: str, font_name: str, font_size: float, max_w: float, max_lines: int) -> List[str]:
    t = (text or "").strip()
    if not t: return []
    words = t.split()
    lines: List[str] = []
    cur = ""
    def flush(line: str):
        if line.strip(): lines.append(line.strip())
    for w in words:
        if stringWidth(w, font_name, font_size) > max_w:
            flush(cur)
            lines.append(_fit_ellipsis(w, font_name, font_size, max_w))
            cur = ""
            if len(lines) >= max_lines: break
            continue
        cand = (cur + " " + w).strip() if cur else w
        if stringWidth(cand, font_name, font_size) <= max_w: cur = cand
        else:
            flush(cur); cur = w
            if len(lines) >= max_lines: break
    if len(lines) < max_lines and cur: lines.append(cur.strip())
    if len(lines) > max_lines: lines = lines[:max_lines]
    if len(lines) == max_lines:
        joined = " ".join(lines)
        if joined != t: lines[-1] = _fit_ellipsis(lines[-1], font_name, font_size, max_w)
    return lines

def _draw_text(c: canvas.Canvas, font: str, size: float, color, x: float, y: float, text: str, align: str = "left"):
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "right": c.drawRightString(x, y, text)
    elif align == "center": c.drawCentredString(x, y, text)
    else: c.drawString(x, y, text)

def _fit_font_size(text: str, font: str, max_size: float, min_size: float, max_w: float) -> float:
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_w: size -= 0.5
    return size

def _draw_text_fit(c: canvas.Canvas, font: str, max_size: float, min_size: float, color, x: float, y: float, text: str, max_w: float, align: str = "left"):
    size = _fit_font_size(text, font, max_size, min_size, max_w)
    _draw_text(c, font, size, color, x, y, text, align=align)

def _draw_footer(c: canvas.Canvas, ui: UI, page_w: float):
    y = 16
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted2"], ui.margin, y, "Finance Bot • Confidential")
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted2"], page_w - ui.margin, y, f"Page {c.getPageNumber()}", align="right")


# =============================================================================
# Components
# =============================================================================

def _draw_header_monthly(c: canvas.Canvas, ui: UI, ctx: Dict, page_w: float, page_h: float, logo_path: Optional[str]):
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
            # Draw logo with preserved aspect ratio (max height 50, auto width)
            from reportlab.lib.utils import ImageReader
            img = ImageReader(logo_path)
            img_w, img_h = img.getSize()
            max_h = 50
            max_w = 110
            # Scale to fit within bounds while preserving aspect ratio
            scale = min(max_w / img_w, max_h / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale
            c.drawImage(logo_path, 25, page_h - 25 - draw_h, width=draw_w, height=draw_h, mask="auto")
        except Exception: pass
    _draw_text(c, ui.fonts["italic"], 10.5, THEME["white"], 140, page_h - 30, f"Generated on {ctx['generated_on']}")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, page_h - 74, "Financial")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, page_h - 114, "Report")
    month_part, year_part = ctx["period_label"].split()
    _draw_text(c, ui.fonts["bold"], 36, THEME["teal"], left_w + 18, page_h - 74, month_part)
    _draw_text(c, ui.fonts["bold"], 36, THEME["teal"], left_w + 18, page_h - 114, year_part)

def _draw_header_range(c: canvas.Canvas, ui: UI, ctx: Dict, page_w: float, page_h: float, logo_path: Optional[str]):
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
            from reportlab.lib.utils import ImageReader
            img = ImageReader(logo_path)
            img_w, img_h = img.getSize()
            max_h = 50
            max_w = 110
            scale = min(max_w / img_w, max_h / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale
            c.drawImage(logo_path, 25, page_h - 25 - draw_h, width=draw_w, height=draw_h, mask="auto")
        except Exception: pass
    _draw_text(c, ui.fonts["italic"], 10.5, THEME["white"], 140, page_h - 30, f"Generated on {ctx['generated_on']}")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, page_h - 74, "Financial")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, page_h - 114, "Report")
    start_text = ctx["start_dt"].strftime("%d-%m-%y")
    end_text = ctx["end_dt"].strftime("%d-%m-%y")
    _draw_text(c, ui.fonts["bold"], 22, THEME["teal"], left_w + 18, page_h - 66, "Periodical Audit")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], left_w + 18, page_h - 86, "Dalam rentang waktu")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["text"], left_w + 18, page_h - 106, f"{start_text} (00:00)")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], left_w + 18, page_h - 122, "hingga")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["text"], left_w + 18, page_h - 138, f"{end_text} (00:00)")

def _draw_kpi_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float, label: str, amount: int, accent, subnote_val: Optional[str] = None):
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    accent_h = 5
    c.saveState()
    c.setFillColor(accent)
    c.roundRect(x, y + h - accent_h, w, accent_h, 2, stroke=0, fill=1)
    c.setFillColor(THEME["card"])
    c.rect(x, y + h - accent_h, w, 1, stroke=0, fill=1)
    c.restoreState()
    
    # Label at top
    _draw_text(c, ui.fonts["semibold"], 11, THEME["muted"], x + 20, y + h - 26, label.upper())
    
    # Amount color
    num_color = accent if accent != THEME["text"] else THEME["text"]
    if label.lower().startswith("profit") and amount < 0: num_color = THEME["danger"]
    
    # Rp and amount on same line
    _draw_text(c, ui.fonts["regular"], 14, THEME["muted2"], x + 20, y + h - 50, "Rp")
    _draw_text_fit(c, ui.fonts["bold"], 26, 18, num_color, x + 46, y + h - 50, format_number(amount), w - 66, align="left")
    
    # Subnote for operational costs - on two lines for clarity
    if subnote_val:
        _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], x + 20, y + 22, "Termasuk Ops. Kantor:")
        _draw_text(c, ui.fonts["semibold"], 10, THEME["text"], x + 20, y + 10, subnote_val)

def _draw_comparison_chart(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float, curr: Dict, prev: Dict):
    """
    Chart perbandingan: Abu-abu = Bulan Lalu, Biru = Bulan Ini
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    
    # Title
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x + 20, y + h - 22, "Perbandingan Bulan Lalu")
    
    # Legend on separate line below title
    leg_y = y + h - 40
    c.setFillColor(THEME["chart_prev"])
    c.roundRect(x + 20, leg_y - 2, 10, 10, 2, stroke=0, fill=1)
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], x + 34, leg_y, "Bulan lalu")
    
    c.setFillColor(THEME["accent"])
    c.roundRect(x + 95, leg_y - 2, 10, 10, 2, stroke=0, fill=1)
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], x + 109, leg_y, "Bulan ini")

    # Chart Area
    chart_h = h - 70
    chart_y = y + 14
    chart_w = w - 40
    chart_x = x + 20
    
    # All metrics use same colors: Gray for previous, Blue for current
    groups = [
        ("Omset", "income_total"),
        ("Pengeluaran", "expense_total"),
        ("Profit", "profit"),
    ]
    
    max_val = 0
    for _, key in groups:
        max_val = max(max_val, abs(int(curr.get(key, 0) or 0)), abs(int(prev.get(key, 0) or 0)))
    if max_val == 0: max_val = 1
    
    group_width = chart_w / len(groups)
    bar_width = (group_width * 0.6) / 2
    gap = 6
    
    for i, (label, key) in enumerate(groups):
        cx = chart_x + i * group_width + (group_width * 0.2)
        val_prev = int(prev.get(key, 0) or 0)
        val_curr = int(curr.get(key, 0) or 0)
        
        # Same colors for all: Gray = previous, Blue = current
        c_prev = THEME["chart_prev"]
        c_curr = THEME["accent"]
        
        h_prev = (abs(val_prev) / max_val) * (chart_h - 28)
        h_curr = (abs(val_curr) / max_val) * (chart_h - 28)
        
        # Draw label at bottom
        _draw_text(c, ui.fonts["semibold"], 10, THEME["text"], cx + bar_width + gap/2, chart_y, label, align="center")
        
        bar_base_y = chart_y + 16
        
        # Previous month bar (left, GRAY)
        c.setFillColor(c_prev)
        c.roundRect(cx, bar_base_y, bar_width, max(2, h_prev), 3, stroke=0, fill=1)
        _draw_text(c, ui.fonts["regular"], 8, THEME["muted"], cx + bar_width/2, bar_base_y + h_prev + 3, format_currency_short(val_prev), align="center")
        
        # Current month bar (right, BLUE)
        c.setFillColor(c_curr)
        c.roundRect(cx + bar_width + gap, bar_base_y, bar_width, max(2, h_curr), 3, stroke=0, fill=1)
        _draw_text(c, ui.fonts["bold"], 8, THEME["text"], cx + bar_width + gap + bar_width/2, bar_base_y + h_curr + 3, format_currency_short(val_curr), align="center")

def _draw_income_share_chart(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, items: List[Tuple[str, float, int]]):
    """
    FIXED: Increased title_h to 35 to prevent overlap with first bar.
    """
    title_h = 35 
    bar_h = 14
    gap = 16
    _draw_text(c, ui.fonts["bold"], 13, THEME["text"], x, y_top - 4, "Grafik Pemasukkan")
    y = y_top - title_h
    label_w = 100
    value_w = 48
    amount_w = 100
    bar_w = max(60, w - label_w - value_w - amount_w - 16)
    bar_x = x + label_w
    value_x = x + w - 4
    for i, (comp, pct, amt) in enumerate(items):
        yy = y - (i * (bar_h + gap))
        label = COMPANY_DISPLAY_COVER.get(comp, comp)
        _draw_text(c, ui.fonts["semibold"], 10.5, THEME["text"], x, yy + 2, label)
        c.setFillColor(THEME["track"])
        c.roundRect(bar_x, yy, bar_w, bar_h, 7, stroke=0, fill=1)
        fill_w = bar_w * (pct / 100.0)
        c.setFillColor(COMPANY_COLOR.get(comp, THEME["accent"]))
        c.roundRect(bar_x, yy, max(4, fill_w), bar_h, 7, stroke=0, fill=1)
        _draw_text(c, ui.fonts["bold"], 10.5, THEME["text"], value_x, yy + 2, f"{pct:.0f}%", align="right")
        _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted2"], value_x, yy - 10, f"Rp {format_number(amt)}", align="right")

def _draw_finished_projects_cover(c: canvas.Canvas, ui: UI, ctx: Dict, page_w: float, y_top: float, title: str, note: str):
    card_x = ui.margin
    card_w = page_w - ui.margin * 2
    card_h = 380  
    y = y_top - card_h
    _draw_card(c, ui, card_x, y, card_w, card_h, shadow=True)
    
    pad = 20
    # Title without accent box - cleaner look
    _draw_text(c, ui.fonts["bold"], 15, THEME["text"], card_x + pad, y + card_h - pad - 6, title)
    
    # Note on single line
    note_y = y + card_h - pad - 24
    _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], card_x + pad, note_y, note)
    
    chart_h = 140 
    chart_y0 = y + pad
    chart_top = chart_y0 + chart_h
    
    c.setStrokeColor(THEME["border"])
    c.setLineWidth(1)
    c.line(card_x + pad, chart_top + 8, card_x + card_w - pad, chart_top + 8)
    
    body_top = note_y - 18
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
        _draw_text(c, ui.fonts["semibold"], 11.5, THEME["text"], cx + 10, col_y0, COMPANY_DISPLAY_COVER.get(comp, comp))
        count = len(ctx["finished_projects"].get(comp, []))
        _draw_text(c, ui.fonts["bold"], 24, COMPANY_COLOR.get(comp, THEME["accent"]), cx + 10, col_y0 - 28, str(count))
        projects = ctx["finished_projects"].get(comp, []) or []
        display = [_project_display_name(p) or p for p in projects]
        yy = col_y0 - 52
        line_h = 12
        if not display:
            _draw_text(c, ui.fonts["regular"], 10, THEME["muted2"], cx + 10, yy, "Tidak ada project")
        else:
            drawn = 0
            for name in display:
                lines = _wrap_lines(name, ui.fonts["regular"], 10, col_w - 20, max_lines=2)
                if not lines: lines = ["-"]
                needed_h = len(lines) * line_h + 6
                if yy - needed_h < body_bottom: break
                _draw_text(c, ui.fonts["regular"], 10, THEME["text"], cx + 10, yy, f"• {lines[0]}")
                if len(lines) > 1:
                    _draw_text(c, ui.fonts["regular"], 10, THEME["text"], cx + 22, yy - line_h, lines[1])
                    yy -= (line_h * 2)
                else: yy -= line_h
                yy -= 6
                drawn += 1
            remaining = len(display) - drawn
            if remaining > 0 and yy - 14 > body_bottom:
                _draw_text(c, ui.fonts["regular"], 10, THEME["muted"], cx + 10, yy - 6, f"+{remaining} lainnya")
                
    chart_items = [(c, ctx["income_share"].get(c, 0.0), ctx.get("income_by_company", {}).get(c, 0)) for c in COMPANY_KEYS]
    _draw_income_share_chart(c, ui, card_x + pad, chart_y0 + chart_h - 8, card_w - 2 * pad, chart_items)

def _draw_company_header(c: canvas.Canvas, ui: UI, ctx: Dict, company: str, page_w: float, page_h: float, header_h: float = 100):
    color = COMPANY_COLOR.get(company, THEME["teal"])
    c.setFillColor(color)
    c.rect(0, page_h - header_h, page_w, header_h, fill=1, stroke=0)
    # Company name - larger and more prominent
    _draw_text(c, ui.fonts["bold"], 36, THEME["white"], ui.margin, page_h - 60, COMPANY_DISPLAY.get(company, company))
    # Period on the right
    month_part, year_part = ctx["period_label"].split()
    _draw_text(c, ui.fonts["bold"], 28, THEME["white"], page_w - ui.margin, page_h - 45, f"{month_part} {year_part}", align="right")
    # Generated date - smaller, at top
    _draw_text(c, ui.fonts["italic"], 9, THEME["white"], ui.margin, page_h - 20, f"Generated on {ctx['generated_on']}")

def _draw_tx_list_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, title: str, items: List[Dict], kind_color, max_items: Optional[int] = None, h: float = 200):
    """
    FIXED: Smaller font and tighter spacing to fit more items.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x + 20, y + h - 26, title)
    c.saveState()
    c.setFillColor(kind_color)
    c.roundRect(x + 20, y + h - 40, 28, 4, 2, stroke=0, fill=1)
    c.restoreState()
    if not items:
        _draw_text(c, ui.fonts["regular"], 11, THEME["muted2"], x + 20, y + h - 58, "Tidak ada data")
        return
    font_name = ui.fonts["regular"]
    font_size = 9.5 
    amount_font = ui.fonts["semibold"]
    amount_size = 10 
    padding_x = 20
    max_display = max_items if max_items is not None else len(items)
    sample = items[:max_display]
    yy = y + h - 52
    drawn = 0
    for i, tx in enumerate(sample):
        desc = (tx.get("keterangan") or "-").strip() or "-"
        prefix = f"{i + 1}."
        prefix_w = stringWidth(prefix + " ", font_name, font_size)
        avail_w = w - 2 * padding_x - prefix_w - 90
        wrapped = _wrap_lines(desc, font_name, font_size, avail_w, max_lines=2) or ["-"]
        line_h = 13.5
        row_h = line_h * len(wrapped) + 10 
        line_y = yy - row_h
        if line_y < y + 16: break
        _draw_text(c, font_name, font_size, THEME["text"], x + padding_x, line_y + row_h - 18, f"{prefix} {wrapped[0]}")
        if len(wrapped) > 1:
            _draw_text(c, font_name, font_size, THEME["muted"], x + padding_x + prefix_w, line_y + row_h - 31, wrapped[1])
        amt = int(tx.get("jumlah", 0) or 0)
        _draw_text(c, amount_font, amount_size, THEME["text"], x + w - padding_x, line_y + row_h - 18, f"Rp {format_number(amt)}", align="right")
        drawn += 1
        yy = line_y
        if i < len(sample) - 1:
            c.saveState()
            c.setStrokeColor(THEME["border_light"])
            c.setLineWidth(1)
            c.line(x + padding_x, yy + 5, x + w - padding_x, yy + 5)
            c.restoreState()
    remaining = len(items) - drawn
    if remaining > 0 and yy - 20 > y + 14:
        _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], x + padding_x, yy - 12, f"+{remaining} lainnya")

def _draw_insight_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, company_details: Dict, h: float = 200):
    """
    FIXED: Enabled text wrapping instead of truncation for insights.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x + 20, y + h - 26, "Insight")
    c.saveState()
    c.setFillColor(THEME["accent"])
    c.roundRect(x + 20, y + h - 40, 24, 4, 2, stroke=0, fill=1)
    c.restoreState()
    
    exp = company_details.get("expense_txs") or []
    sal = company_details.get("salary_txs") or []
    cards = company_details.get("finished_cards") or []

    # Helper to format line
    def fmt_line(label, val_txt, amt):
        return f"{label}: {val_txt} ({format_currency(amt)})"

    lines = []
    if exp:
        top = exp[0]
        lines.append(fmt_line("Pengeluaran terbesar", top.get('keterangan',''), int(top.get('jumlah',0) or 0)))
    else: lines.append("Pengeluaran terbesar: -")
    
    if sal:
        lines.append(fmt_line("Fee terbesar", sal[0].get('keterangan',''), int(sal[0].get('jumlah',0) or 0)))
        lines.append(fmt_line("Fee terkecil", sal[-1].get('keterangan','') if len(sal)>1 else sal[0].get('keterangan',''), int((sal[-1] if len(sal)>1 else sal[0]).get('jumlah',0) or 0)))
    else:
        lines.append("Fee terbesar: -")
        lines.append("Fee terkecil: -")
        
    if cards:
        best = max(cards, key=lambda x: int(x["metrics"]["profit"]))
        worst = min(cards, key=lambda x: int(x["metrics"]["profit"]))
        lines.append(f"Project terbaik: {best['name']} ({format_currency(int(best['metrics']['profit']))})")
        lines.append(f"Project terendah: {worst['name']} ({format_currency(int(worst['metrics']['profit']))})")
    else:
        lines.append("Project terbaik: -")
        lines.append("Project terendah: -")

    yy = y + h - 56
    font_sz = 9.5
    for line in lines:
        wrapped = _wrap_lines(line, ui.fonts["regular"], font_sz, w - 40, max_lines=2)
        for wline in wrapped:
            if yy < y + 10: break
            _draw_text(c, ui.fonts["regular"], font_sz, THEME["text"], x + 20, yy, wline)
            yy -= 14
        yy -= 4

def _draw_project_card(c: canvas.Canvas, ui: UI, x: float, y_top: float, w: float, h: float, idx: int, company: str, proj: Dict):
    """
    FIXED: Improved layout - project name closer to values, better spacing.
    """
    y = y_top - h
    _draw_card(c, ui, x, y, w, h, shadow=True)
    accent = COMPANY_COLOR.get(company, THEME["accent"])
    accent_h = 5
    c.saveState()
    c.setFillColor(accent)
    c.roundRect(x, y + h - accent_h, w, accent_h + 2, 2, stroke=0, fill=1)
    c.setFillColor(THEME["card"])
    c.rect(x, y + h - accent_h, w, 1, stroke=0, fill=1)
    c.restoreState()

    name = proj.get("name", "Project")
    # Project name - positioned closer to profit info
    name_display = _fit_ellipsis(f"{idx}. {name}", ui.fonts["bold"], 14, w - 180)
    _draw_text(c, ui.fonts["bold"], 14, THEME["text"], x + 22, y + h - 28, name_display)

    metrics = proj.get("metrics", {}) or {}
    profit = int(metrics.get("profit", 0) or 0)
    margin = int(metrics.get("margin_pct", 0) or 0)
    profit_color = THEME["success"] if profit >= 0 else THEME["danger"]
    
    # Profit info - positioned on same line as project name
    _draw_text(c, ui.fonts["semibold"], 10, THEME["muted"], x + w - 22, y + h - 18, "Profit Kotor", align="right")
    profit_text = f"Rp {format_number(profit)}  ({margin}%)"
    _draw_text_fit(c, ui.fonts["bold"], 13, 10, profit_color, x + w - 22, y + h - 33, profit_text, 170, align="right")

    timeline = proj.get("timeline", {}) or {}
    start_dt = timeline.get("start")
    finish_dt = timeline.get("finish")
    start_txt = start_dt.strftime("%d %b %Y") if isinstance(start_dt, datetime) else "-"
    finish_txt = finish_dt.strftime("%d %b %Y") if isinstance(finish_dt, datetime) else "-"
    
    # Dates - positioned right below project name
    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], x + 22, y + h - 45, f"Mulai: {start_txt}")
    _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted"], x + 22, y + h - 58, f"Selesai: {finish_txt}")

    # Divider line
    c.saveState()
    c.setStrokeColor(THEME["border_light"])
    c.setLineWidth(1)
    c.line(x + 22, y + h - 68, x + w - 22, y + h - 68)
    c.restoreState()

    # Layout Grid for values
    col1_x = x + 22
    col_w = (w - 44) / 4.0

    def draw_pair(ix: int, label: str, val_text: str, y_base: float, val_color=THEME["text"]):
        cx = col1_x + ix * col_w
        # Label directly above value
        _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], cx, y_base + 14, label)
        # Value
        _draw_text_fit(c, ui.fonts["bold"], 11, 9, val_color, cx, y_base, val_text, col_w - 8, align="left")

    # Row 1 (Income side) - positioned closer to dates
    y_r1 = y + 48
    draw_pair(0, "Nilai", f"Rp {format_number(int(metrics.get('total_income',0) or 0))}", y_r1)
    draw_pair(1, "DP", f"Rp {format_number(int(metrics.get('dp',0) or 0))}", y_r1)
    draw_pair(2, "DP 2", f"Rp {format_number(int(metrics.get('dp2',0) or 0))}", y_r1)
    draw_pair(3, "Pelunasan", f"Rp {format_number(int(metrics.get('pelunasan',0) or 0))}", y_r1)

    # Row 2 (Expense side)
    y_r2 = y + 14
    draw_pair(0, "Pengeluaran", f"Rp {format_number(int(metrics.get('total_expense',0) or 0))}", y_r2, THEME["danger"])
    draw_pair(1, "Gaji", f"Rp {format_number(int(metrics.get('total_salary',0) or 0))}", y_r2)

    # Max expense - in columns 3 & 4, laid out vertically
    max_exp = proj.get("max_expense")
    cx = col1_x + 2 * col_w
    
    # Label
    _draw_text(c, ui.fonts["regular"], 9, THEME["muted"], cx, y_r2 + 14, "Pengeluaran Terbesar")
    
    if max_exp:
        desc = max_exp.get("keterangan", "")
        amt = int(max_exp.get("jumlah", 0) or 0)
        
        # Item name directly below label
        desc_fit = _fit_ellipsis(desc, ui.fonts["regular"], 9.5, col_w - 10)
        _draw_text(c, ui.fonts["regular"], 9.5, THEME["text"], cx, y_r2, desc_fit)
        
        # Amount in column 4 (same row, aligned left like others)
        amt_str = f"Rp {format_number(amt)}"
        cx4 = col1_x + 3 * col_w
        _draw_text(c, ui.fonts["bold"], 11, THEME["danger"], cx4, y_r2, amt_str)
    else:
        _draw_text(c, ui.fonts["regular"], 9.5, THEME["muted2"], cx, y_r2, "-")


# =============================================================================
# Page drawing
# =============================================================================

def draw_cover_monthly(c: canvas.Canvas, ui: UI, ctx: Dict, logo_path: Optional[str] = None):
    page_w, page_h = A4
    c.setFillColor(THEME["bg"])
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    _draw_header_monthly(c, ui, ctx, page_w, page_h, logo_path)
    y = page_h - 190 - 28
    kpi_h = 100
    gap = 18
    content_x = ui.margin
    content_w = page_w - 2 * ui.margin
    kpi_w = (content_w - 2 * gap) / 3.0
    summary = ctx["summary"]
    prev = ctx["prev_summary"]
    office_val = f"Rp {format_number(int(summary['office_expense']))}"
    _draw_kpi_card(c, ui, content_x + 0 * (kpi_w + gap), y, kpi_w, kpi_h, "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(c, ui, content_x + 1 * (kpi_w + gap), y, kpi_w, kpi_h, "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"], subnote_val=office_val)
    _draw_kpi_card(c, ui, content_x + 2 * (kpi_w + gap), y, kpi_w, kpi_h, "Profit", int(summary["profit"]), THEME["teal"])
    y -= (kpi_h + 28)
    pill_y = y
    for i, (label_key, label_text, curr_key) in enumerate([("income", "Bulan lalu", "income_total"), ("expense", "Bulan lalu", "expense_total"), ("profit", "Bulan lalu", "profit")]):
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
    y -= 70
    _draw_finished_projects_cover(c, ui, ctx, page_w, y, "Project yang Selesai Bulan ini", "Adalah Project, yang telah tuntas pada bulan ini. Untuk mulainya tidak harus bulan ini.")
    _draw_footer(c, ui, page_w)

def draw_cover_periodical(c: canvas.Canvas, ui: UI, ctx: Dict, logo_path: Optional[str] = None):
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
    office_val = f"Rp {format_number(int(summary['office_expense']))}"
    _draw_kpi_card(c, ui, content_x + 0 * (kpi_w + gap), y, kpi_w, kpi_h, "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(c, ui, content_x + 1 * (kpi_w + gap), y, kpi_w, kpi_h, "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"], subnote_val=office_val)
    _draw_kpi_card(c, ui, content_x + 2 * (kpi_w + gap), y, kpi_w, kpi_h, "Profit", int(summary["profit"]), THEME["teal"])
    y -= (kpi_h + 28)
    _draw_finished_projects_cover(c, ui, ctx, page_w, y, "Project yang Selesai dalam Periode ini", "Adalah Project yang tuntas dalam rentang waktu yang dipilih.")
    _draw_footer(c, ui, page_w)

def _estimate_company_page_height(ui: UI, company_details: Dict, base_h: float = 1700) -> float:
    cards = company_details.get("finished_cards") or []
    card_h = 150 
    card_gap = 14
    n_cards = len(cards)
    if n_cards == 0: return base_h
    extra_h = n_cards * (card_h + card_gap) + 60
    return base_h + extra_h

def draw_company_page(c: canvas.Canvas, ui: UI, ctx: Dict, company: str, page_h: float):
    page_w = A4[0]
    c.setFillColor(THEME["bg"])
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    _draw_company_header(c, ui, ctx, company, page_w, page_h, header_h=150)
    details = ctx["company_details"][company]
    summary = details["summary"]
    prev = details["prev_summary"]
    content_x = ui.margin
    content_w = page_w - 2 * ui.margin
    y = page_h - 150 - 28
    kpi_h = 100
    gap = 18
    kpi_w = (content_w - 2 * gap) / 3.0
    _draw_kpi_card(c, ui, content_x + 0 * (kpi_w + gap), y, kpi_w, kpi_h, "Omset Total", int(summary["income_total"]), THEME["text"])
    _draw_kpi_card(c, ui, content_x + 1 * (kpi_w + gap), y, kpi_w, kpi_h, "Pengeluaran Total", int(summary["expense_total"]), THEME["pink"])
    _draw_kpi_card(c, ui, content_x + 2 * (kpi_w + gap), y, kpi_w, kpi_h, "Profit", int(summary["profit"]), THEME["teal"])
    y -= (kpi_h + 24)
    left_w = 260
    row_h = 142
    _draw_card(c, ui, content_x, y - row_h, left_w, row_h, shadow=True)
    _draw_text(c, ui.fonts["bold"], 13, THEME["text"], content_x + 16, y - 22, "Bulan lalu (ringkas)")
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
    col_gap = 20
    col_w = (content_w - col_gap) / 2.0
    
    # INCREASED height for lists to fit more items
    list_h = 260 
    
    _draw_tx_list_card(c, ui, content_x, y, col_w, "List Pemasukan", details["income_txs"], THEME["teal"], max_items=None, h=list_h)
    _draw_tx_list_card(c, ui, content_x + col_w + col_gap, y, col_w, "List Pengeluaran", details["expense_txs"], THEME["pink"], max_items=None, h=list_h)
    y -= (list_h + 20)
    _draw_tx_list_card(c, ui, content_x, y, col_w, "List Gaji", details["salary_txs"], COMPANY_COLOR.get(company, THEME["teal"]), max_items=None, h=list_h)
    _draw_insight_card(c, ui, content_x + col_w + col_gap, y, col_w, details, h=list_h)
    y -= (list_h + 28)
    _draw_text(c, ui.fonts["bold"], 16, THEME["text"], content_x, y, "Finished Projects")
    _draw_text(c, ui.fonts["regular"], 10.5, THEME["muted"], content_x, y - 18, "Project yang tuntas pada bulan ini (mulai bisa dari bulan lain).")
    y -= 36
    cards = details.get("finished_cards") or []
    if not cards:
        _draw_text(c, ui.fonts["regular"], 11, THEME["muted2"], content_x, y - 10, "Tidak ada project selesai pada bulan ini.")
        _draw_footer(c, ui, page_w)
        return
    card_gap = 14
    card_h = 150 
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
# PDF generators
# =============================================================================

def generate_pdf_report_v4_monthly(year: int, month: int, output_dir: Optional[str] = None) -> str:
    ctx = _build_context_monthly(year, month)
    fonts = register_fonts()
    ui = UI(fonts=fonts)
    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    fname = _safe_filename(f"Laporan_Keuangan_{ctx['period_label']}") + ".pdf"
    output_path = os.path.join(out_dir, fname)
    logo_path = _get_logo_path()
    c = canvas.Canvas(output_path, pagesize=A4)
    draw_cover_monthly(c, ui, ctx, logo_path=logo_path)
    c.showPage()
    for comp in COMPANY_KEYS:
        page_h = _estimate_company_page_height(ui, ctx["company_details"][comp], base_h=1700)
        c.setPageSize((A4[0], page_h))
        draw_company_page(c, ui, ctx, comp, page_h=page_h)
        c.showPage()
    c.save()
    secure_log("INFO", f"PDF generated: {output_path}")
    return output_path

def generate_pdf_report_v4_range(start_dt: datetime, end_dt: datetime, output_dir: Optional[str] = None) -> str:
    ctx = _build_context_range(start_dt, end_dt)
    fonts = register_fonts()
    ui = UI(fonts=fonts)
    out_dir = output_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    fname = _safe_filename(f"Laporan_Keuangan_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}") + ".pdf"
    output_path = os.path.join(out_dir, fname)
    logo_path = _get_logo_path()
    c = canvas.Canvas(output_path, pagesize=A4)
    draw_cover_periodical(c, ui, ctx, logo_path=logo_path)
    c.save()
    secure_log("INFO", f"PDF generated: {output_path}")
    return output_path

def generate_pdf_report(year: int, month: int, output_dir: Optional[str] = None, **kwargs) -> str:
    return generate_pdf_report_v4_monthly(year, month, output_dir=output_dir)

def generate_pdf_from_input(period_input: str, output_dir: Optional[str] = None) -> str:
    s = _normalize_user_input(period_input)
    if not s:
        raise PDFInputError("Format perintah kosong.")
    rng = parse_range_input(s)
    if rng:
        start_dt, end_dt = rng
        return generate_pdf_report_v4_range(start_dt, end_dt, output_dir=output_dir)
    year, month = parse_month_input(s)
    return generate_pdf_report_v4_monthly(year, month, output_dir=output_dir)

if __name__ == "__main__":
    tests = ["2026-01", "01-2026", "januari 2026", "12-01-2026 - 20-01-2026"]
    for t in tests:
        try:
            s = _normalize_user_input(t)
            rng = parse_range_input(s)
            if rng: print("[RANGE]", t, "=>", rng[0].date(), rng[1].date())
            else:
                y, m = parse_month_input(s)
                print("[MONTH]", t, "=>", y, m)
        except Exception as e:
            print("[ERR]", t, "=>", e)