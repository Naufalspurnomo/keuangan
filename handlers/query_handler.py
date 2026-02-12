"""
Smart Query Handler - Hybrid (Rules + Data + AI fallback)

Features:
- Project queries with evidence/rincian per transaksi
- Wallet/dompet queries with descriptor filtering
- Finished project listing
- General financial summary
- AI fallback for complex natural language questions
"""

import logging
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher

from ai_helper import groq_client
from config.constants import OPERASIONAL_SHEET_NAME
from config.wallets import resolve_dompet_from_text
from security import sanitize_input, detect_prompt_injection
from sheets_helper import (
    format_data_for_ai,
    get_all_data,
    get_hutang_summary,
    get_summary,
    get_wallet_balances,
    find_open_hutang,
)
from utils.normalizer import normalize_nyeleneh_text
from utils.parsers import extract_project_name_from_text

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 30
EVIDENCE_LIMIT_DEFAULT = 5
EVIDENCE_LIMIT_DETAIL = 10

PROJECT_PREFIX_RE = re.compile(r"^\s*(holla|hojja)\s*[-:]\s*", re.IGNORECASE)
PROJECT_PHASE_RE = re.compile(r"\s*\((start|finish)\)\s*$", re.IGNORECASE)
PROJECT_QUERY_STOPWORDS = {
    "bot", "tolong", "dong", "berapa", "gimana", "bagaimana", "cek", "check", "lihat",
    "pengeluaran", "pemasukan", "income", "expense", "biaya", "total", "rekap", "status",
    "projek", "project", "proyek", "projectnya", "projeknya", "hari", "ini", "kemarin",
    "minggu", "bulan", "tahun", "terakhir", "detail", "rinci", "transaksi", "laporan",
    "berapa?", "jawab", "dengan", "yang", "sudah", "secara", "keseluruhan", "semua",
    "sebutkan", "tampilkan", "kasih", "tau", "tahu", "mana", "apa", "saja",
    "dompet", "wallet", "saldo", "fee", "gaji",
}

# Extra stopwords for dompet context (avoid matching dompet name as descriptor)
WALLET_NAME_TOKENS = {
    "bali", "surabaya", "sby", "evan", "holla", "hojja", "texturin",
}


def _format_idr(amount: int) -> str:
    try:
        return f"Rp {int(amount):,}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _normalize_project_label(name: str) -> str:
    """Normalize project names so queries can match prefixed/suffixed project labels."""
    if not name:
        return ""
    normalized = _normalize_text(name)
    normalized = PROJECT_PREFIX_RE.sub("", normalized)
    normalized = PROJECT_PHASE_RE.sub("", normalized)
    normalized = normalized.replace(" - ", " ").replace("_", " ")
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    return " ".join(normalized.split())


# ===================== MISSING FUNCTIONS (FIXED) =====================

def _filter_rows_by_descriptors(rows: list, tokens: list) -> tuple:
    """
    Filter transaction rows by descriptor tokens found in keterangan/nama_projek.
    Returns (filtered_rows, mode) where mode is 'strict', 'loose', or 'none'.
    
    - strict: ALL tokens must match (AND logic)
    - loose: ANY token matches (OR logic), used as fallback if strict yields 0
    - none: no filtering applied
    """
    if not tokens or not rows:
        return rows, "none"

    # Try strict first (all tokens must appear)
    strict_rows = []
    for row in rows:
        haystack = _normalize_text(
            f"{row.get('keterangan', '')} {row.get('nama_projek', '')}"
        )
        if all(token in haystack for token in tokens):
            strict_rows.append(row)

    if strict_rows:
        return strict_rows, "strict"

    # Fallback to loose (any token)
    loose_rows = []
    for row in rows:
        haystack = _normalize_text(
            f"{row.get('keterangan', '')} {row.get('nama_projek', '')}"
        )
        if any(token in haystack for token in tokens):
            loose_rows.append(row)

    if loose_rows:
        return loose_rows, "loose"

    return rows, "none"


def _format_evidence_line(d: dict) -> str:
    """Format a single transaction row as a readable evidence line."""
    amt = _format_idr(d.get("jumlah", 0))
    tipe = d.get("tipe", "")
    ket = (d.get("keterangan", "") or "").strip()
    tanggal = d.get("tanggal", "")
    sheet = d.get("company_sheet", "")
    projek = d.get("nama_projek", "")

    # Truncate long keterangan
    if len(ket) > 60:
        ket = ket[:57] + "..."

    # Build line
    tipe_icon = "📥" if tipe == "Pemasukan" else "📤"
    parts = [f"{tipe_icon} {tanggal}", amt]
    if ket:
        parts.append(f'"{ket}"')
    if projek and projek.lower() not in ket.lower():
        parts.append(f"[{projek}]")
    if sheet:
        parts.append(f"({sheet})")

    return "  • " + " — ".join(parts)


def _extract_query_descriptor_tokens(query: str, project_name: str = "", extra_exclude: set = None) -> list:
    """
    Get descriptive tokens from query (e.g., 'fee', 'sugeng') excluding boilerplate words.
    
    Args:
        query: The user's query text
        project_name: Project name to exclude from tokens
        extra_exclude: Additional tokens to exclude (e.g., dompet name parts)
    """
    query_tokens = re.findall(r"[a-zA-Z0-9]{3,}", _normalize_text(query))
    project_tokens = set(re.findall(r"[a-zA-Z0-9]{3,}", _normalize_project_label(project_name)))
    exclude = PROJECT_QUERY_STOPWORDS | project_tokens | WALLET_NAME_TOKENS
    if extra_exclude:
        exclude |= extra_exclude

    tokens = []
    for token in query_tokens:
        if token in exclude:
            continue
        tokens.append(token)
    return sorted(set(tokens))


def _wants_detail(norm_text: str) -> bool:
    """Check if user wants detailed/rinci response."""
    return any(k in norm_text for k in [
        "detail", "rinci", "transaksi", "terakhir", "riwayat", "list",
        "sebutkan", "tampilkan", "jelaskan",
    ])


def _evidence_limit(norm_text: str) -> int:
    """How many evidence lines to show based on user's request."""
    if _wants_detail(norm_text):
        return EVIDENCE_LIMIT_DETAIL
    return EVIDENCE_LIMIT_DEFAULT


def _append_evidence(lines: list, rows: list, limit: int, title: str = "Rincian transaksi:"):
    """Append evidence lines to output."""
    if not rows:
        return
    recents = _recent_transactions(rows, limit)
    if recents:
        lines.append(f"\n{title}")
        for d in recents:
            lines.append(_format_evidence_line(d))
        remaining = len(rows) - len(recents)
        if remaining > 0:
            lines.append(f"  ... dan {remaining} transaksi lainnya")


# ===================== ORIGINAL HELPERS =====================

def _parse_date(date_str: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue
    return datetime.min


def _extract_days(text: str) -> tuple:
    text = text or ""

    if any(k in text for k in ["sejak awal", "alltime", "all time", "keseluruhan", "seluruh"]):
        return None, "sepanjang data"

    # "semua" only triggers all-time if NOT followed by project/specific context
    if re.search(r"\bsemua\b", text) and not re.search(r"\bsemua\s+(projek|project|transaksi|dompet)", text):
        return None, "sepanjang data"

    if "hari ini" in text or "hari ini?" in text:
        return 1, "hari ini"

    if "kemarin" in text:
        return 2, "2 hari terakhir"

    if "minggu ini" in text:
        return 7, "7 hari terakhir"

    if "bulan ini" in text:
        return 30, "30 hari terakhir"

    if "tahun ini" in text:
        return 365, "365 hari terakhir"

    match = re.search(r"\b(\d{1,3})\s*(hari|hr|minggu|bulan|tahun)\b", text)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        if unit in ["hari", "hr"]:
            return num, f"{num} hari terakhir"
        if unit == "minggu":
            days = num * 7
            return days, f"{days} hari terakhir"
        if unit == "bulan":
            days = num * 30
            return days, f"{days} hari terakhir"
        if unit == "tahun":
            days = num * 365
            return days, f"{days} hari terakhir"

    if "total" in text:
        return None, "sepanjang data"

    return DEFAULT_DAYS, f"{DEFAULT_DAYS} hari terakhir"


def _strip_context_tags(ctx: str) -> str:
    if not ctx:
        return ""
    lines = []
    for line in ctx.splitlines():
        if line.strip().startswith("<") and line.strip().endswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _recent_transactions(rows: list, limit: int = 3) -> list:
    if not rows:
        return []
    sorted_rows = sorted(rows, key=lambda d: _parse_date(d.get("tanggal", "")), reverse=True)
    return sorted_rows[:limit]


def _match_project_name(query: str, by_projek: dict) -> tuple:
    if not by_projek:
        return None, 0.0

    query_norm = _normalize_text(query)
    query_project_hint = _normalize_project_label(extract_project_name_from_text(query) or "")
    query_without_keyword = _normalize_project_label(
        re.sub(r"\b(?:projek|project|proyek)\b", " ", query_norm, flags=re.IGNORECASE)
    )

    best = None
    best_score = 0.0

    for info in by_projek.values():
        name = info.get("name", "")
        if not name:
            continue

        name_norm = _normalize_text(name)
        base_name = _normalize_project_label(name)
        if not base_name:
            continue

        score = 0.0

        if name_norm in query_norm or base_name in query_norm:
            score = max(score, 1.0)

        if query_project_hint:
            if query_project_hint in base_name or base_name in query_project_hint:
                score = max(score, 0.96)
            else:
                score = max(score, SequenceMatcher(None, query_project_hint, base_name).ratio())

        if query_without_keyword:
            score = max(score, SequenceMatcher(None, query_without_keyword, base_name).ratio() * 0.9)

        score = max(score, SequenceMatcher(None, query_norm, name_norm).ratio() * 0.75)

        if score > best_score:
            best = info
            best_score = score

    if best_score >= 0.48:
        return best, best_score

    return None, 0.0


def _project_dompet_hint(project_rows: list) -> str:
    if not project_rows:
        return ""
    dompet_counts = Counter()
    for d in project_rows:
        comp = d.get("company_sheet", "")
        if comp and comp != OPERASIONAL_SHEET_NAME:
            dompet_counts[comp] += 1
    if not dompet_counts:
        return ""
    dompet = dompet_counts.most_common(1)[0][0]
    return dompet


# ===================== QUERY HANDLERS =====================

def _handle_wallet_query(dompet: str, norm_text: str, days: int, period_label: str, raw_query: str = "") -> str:
    wants_balance = any(k in norm_text for k in ["saldo", "balance", "sisa"])
    wants_income = any(k in norm_text for k in ["pemasukan", "income", "masuk"])
    wants_expense = any(k in norm_text for k in ["pengeluaran", "expense", "keluar", "biaya"])
    show_detail = _wants_detail(norm_text)

    if wants_balance and not (wants_income or wants_expense):
        balances = get_wallet_balances()
        info = balances.get(dompet)
        if not info:
            return f"Dompet {dompet} tidak ditemukan."
        lines = [
            f"💼 Saldo dompet {dompet}",
            f"💰 Saldo saat ini: {_format_idr(info.get('saldo', 0))}",
            f"📥 Total masuk: {_format_idr(info.get('pemasukan', 0))}",
            f"📤 Total keluar: {_format_idr(info.get('pengeluaran', 0))}",
        ]
        op_debit = info.get("operational_debit", 0)
        if op_debit:
            lines.append(f"🏢 Potongan operasional: {_format_idr(op_debit)}")
        hutang_open = info.get("utang_open_in", 0)
        if hutang_open:
            lines.append(f"💳 Penyesuaian hutang OPEN: {_format_idr(hutang_open)}")
        return "\n".join(lines)

    data = get_all_data(days) if days is not None else get_all_data(None)
    dompet_data = [d for d in data if d.get("company_sheet") == dompet]

    if not dompet_data:
        return f"Belum ada transaksi untuk dompet {dompet} ({period_label})."

    # Extract descriptor tokens, excluding dompet name parts
    dompet_name_tokens = set(re.findall(r"[a-zA-Z0-9]{2,}", _normalize_text(dompet)))
    descriptor_tokens = _extract_query_descriptor_tokens(
        raw_query or norm_text,
        extra_exclude=dompet_name_tokens | {"dompet", "wallet", "saldo"}
    )
    scoped_rows, scope_mode = _filter_rows_by_descriptors(dompet_data, descriptor_tokens)
    scoped_applied = bool(descriptor_tokens and scope_mode in {"strict", "loose"})

    income = sum(d["jumlah"] for d in scoped_rows if d.get("tipe") == "Pemasukan")
    expense = sum(d["jumlah"] for d in scoped_rows if d.get("tipe") == "Pengeluaran")
    net = income - expense

    lines = [f"💼 Dompet {dompet} ({period_label})"]

    if scoped_applied:
        lines.append(f"🔍 Filter: {', '.join(descriptor_tokens)}")
        lines.append(f"📋 {len(scoped_rows)} dari {len(dompet_data)} transaksi cocok")

    if wants_income and not wants_expense:
        lines.append(f"\n📥 Pemasukan: {_format_idr(income)}")
    elif wants_expense and not wants_income:
        lines.append(f"\n📤 Pengeluaran: {_format_idr(expense)}")
    else:
        lines.append(f"\n📥 Pemasukan: {_format_idr(income)}")
        lines.append(f"📤 Pengeluaran: {_format_idr(expense)}")
        lines.append(f"💰 Net: {_format_idr(net)}")

    # Show evidence when filtered or detail requested
    if scoped_applied or show_detail:
        limit = _evidence_limit(norm_text)
        title = "📝 Transaksi yang cocok:" if scoped_applied else "📝 Transaksi terakhir:"
        _append_evidence(lines, scoped_rows, limit, title)

    return "\n".join(lines)


def _handle_operational_query(norm_text: str, days: int, period_label: str) -> str:
    data = get_all_data(days) if days is not None else get_all_data(None)
    ops = [d for d in data if d.get("company_sheet") == OPERASIONAL_SHEET_NAME]
    if not ops:
        return f"Belum ada data operasional ({period_label})."

    total = sum(d["jumlah"] for d in ops if d.get("tipe") == "Pengeluaran")
    show_detail = _wants_detail(norm_text)

    lines = [
        f"🏢 Operasional Kantor ({period_label})",
        f"📤 Total pengeluaran: {_format_idr(total)}",
        f"📋 {len(ops)} transaksi",
    ]

    if show_detail:
        _append_evidence(lines, ops, EVIDENCE_LIMIT_DETAIL, "📝 Transaksi operasional:")

    return "\n".join(lines)


def _handle_hutang_query(norm_text: str, days: int, period_label: str, dompet: str = None) -> str:
    if dompet:
        open_as_borrower = find_open_hutang(yang_hutang=dompet)
        open_as_lender = find_open_hutang(yang_dihutangi=dompet)

        borrower_total = sum(int(row.get("jumlah", 0) or 0) for row in open_as_borrower)
        lender_total = sum(int(row.get("jumlah", 0) or 0) for row in open_as_lender)
        net = lender_total - borrower_total

        lines = [
            f"💳 Status utang dompet {dompet}",
            f"📤 Masih berutang: {_format_idr(borrower_total)} ({len(open_as_borrower)} transaksi)",
            f"📥 Piutang belum lunas: {_format_idr(lender_total)} ({len(open_as_lender)} transaksi)",
            f"💰 Posisi bersih: {_format_idr(net)}",
        ]
        return "\n".join(lines)

    summary = get_hutang_summary(days=days or 0)
    lines = [
        f"💳 Ringkasan Utang ({period_label})",
        f"🔴 OPEN: {_format_idr(summary.get('open_total', 0))} ({summary.get('open_count', 0)} transaksi)",
        f"✅ PAID: {_format_idr(summary.get('paid_total', 0))} ({summary.get('paid_count', 0)} transaksi)",
        f"❌ CANCELLED: {_format_idr(summary.get('cancelled_total', 0))} ({summary.get('cancelled_count', 0)} transaksi)",
    ]
    return "\n".join(lines)


def _handle_project_query(query: str, norm_text: str, days: int, period_label: str) -> str:
    wants_profit = any(k in norm_text for k in ["untung", "rugi", "laba", "profit"])
    wants_income = any(k in norm_text for k in ["pemasukan", "income", "masuk"])
    wants_expense = any(k in norm_text for k in ["pengeluaran", "expense", "keluar", "biaya"])
    show_detail = _wants_detail(norm_text)

    summary = get_summary(days) if days is not None else get_summary(365)
    match, _score = _match_project_name(query, summary.get("by_projek", {}))
    if not match and days is not None:
        summary = get_summary(365)
        match, _score = _match_project_name(query, summary.get("by_projek", {}))

    if not match:
        return "Nama projek belum ditemukan di data. Coba tulis nama projek lebih spesifik."

    project_name = match.get("name", "Projek")
    target_base_name = _normalize_project_label(project_name)

    data = get_all_data(days) if days is not None else get_all_data(None)
    project_rows = []
    for d in data:
        row_project_name = d.get("nama_projek", "")
        row_base_name = _normalize_project_label(row_project_name)
        if not row_base_name:
            continue
        if row_base_name == target_base_name or target_base_name in row_base_name or row_base_name in target_base_name:
            project_rows.append(d)

    # Descriptor filtering (e.g., "fee sugeng" within project)
    descriptor_tokens = _extract_query_descriptor_tokens(query, project_name)
    filtered_rows = project_rows
    is_scoped_by_descriptor = False

    if descriptor_tokens:
        scoped_rows = []
        for row in project_rows:
            haystack = f"{_normalize_text(row.get('keterangan', ''))} {_normalize_text(row.get('nama_projek', ''))}"
            if all(token in haystack for token in descriptor_tokens):
                scoped_rows.append(row)
        if not scoped_rows:
            for row in project_rows:
                haystack = f"{_normalize_text(row.get('keterangan', ''))} {_normalize_text(row.get('nama_projek', ''))}"
                if any(token in haystack for token in descriptor_tokens):
                    scoped_rows.append(row)
        if scoped_rows:
            filtered_rows = scoped_rows
            is_scoped_by_descriptor = True

    income = sum(d.get("jumlah", 0) for d in filtered_rows if d.get("tipe") == "Pemasukan")
    expense = sum(d.get("jumlah", 0) for d in filtered_rows if d.get("tipe") == "Pengeluaran")
    profit = income - expense
    status = "UNTUNG ✅" if profit > 0 else "RUGI ❌" if profit < 0 else "NETRAL"

    dompet_hint = _project_dompet_hint(filtered_rows or project_rows)
    dompet_txt = f" | Dompet: {dompet_hint}" if dompet_hint else ""

    lines = [f"📊 Projek {project_name} ({period_label}){dompet_txt}"]

    if is_scoped_by_descriptor:
        lines.append(f"🔍 Filter: {', '.join(descriptor_tokens)}")
        lines.append(f"📋 {len(filtered_rows)} dari {len(project_rows)} transaksi cocok")

    if wants_income and not wants_expense:
        lines.append(f"\n📥 Pemasukan: {_format_idr(income)}")
    elif wants_expense and not wants_income:
        lines.append(f"\n📤 Pengeluaran: {_format_idr(expense)}")
    else:
        lines.append(f"\n📥 Pemasukan: {_format_idr(income)}")
        lines.append(f"📤 Pengeluaran: {_format_idr(expense)}")

    if wants_profit or (not wants_income and not wants_expense):
        lines.append(f"💰 Laba/Rugi: {_format_idr(profit)} ({status})")
    
    lines.append(f"📋 Total transaksi: {len(filtered_rows)}")

    # Always show evidence when descriptor-filtered, or when detail requested
    show_limit = _evidence_limit(norm_text)
    if is_scoped_by_descriptor or show_detail:
        title = "📝 Transaksi yang cocok:" if is_scoped_by_descriptor else "📝 Transaksi terakhir:"
        _append_evidence(lines, filtered_rows, show_limit, title)

    return "\n".join(lines)


def _handle_finished_projects_query(norm_text: str, days: int, period_label: str) -> str:
    """Handle queries about finished projects."""
    data = get_all_data(days) if days is not None else get_all_data(None)

    # Find all unique project names with (Finish) marker
    finished_projects = {}
    for d in data:
        proj = d.get("nama_projek", "").strip()
        if not proj:
            continue
        proj_lower = proj.lower()
        if "(finish)" in proj_lower or "finish" in proj_lower:
            base = _normalize_project_label(proj)
            if base not in finished_projects:
                finished_projects[base] = {
                    "name": proj,
                    "rows": [],
                }
            finished_projects[base]["rows"].append(d)

    if not finished_projects:
        return f"Tidak ada projek yang finish ({period_label})."

    show_detail = _wants_detail(norm_text)
    lines = [
        f"🏁 Projek Finish ({period_label})",
        f"📋 {len(finished_projects)} projek selesai",
    ]

    for i, (_, info) in enumerate(sorted(finished_projects.items(), key=lambda x: -len(x[1]["rows"])), 1):
        rows = info["rows"]
        name = info["name"]
        income = sum(d.get("jumlah", 0) for d in rows if d.get("tipe") == "Pemasukan")
        expense = sum(d.get("jumlah", 0) for d in rows if d.get("tipe") == "Pengeluaran")
        profit = income - expense
        status = "UNTUNG ✅" if profit > 0 else "RUGI ❌" if profit < 0 else "NETRAL"
        dompet = _project_dompet_hint(rows)

        lines.append(f"\n{'─' * 30}")
        lines.append(f"{i}️⃣ {name}")
        if dompet:
            lines.append(f"   Dompet: {dompet}")
        lines.append(f"   📥 Pemasukan: {_format_idr(income)} ({sum(1 for d in rows if d.get('tipe') == 'Pemasukan')} tx)")
        lines.append(f"   📤 Pengeluaran: {_format_idr(expense)} ({sum(1 for d in rows if d.get('tipe') == 'Pengeluaran')} tx)")
        lines.append(f"   💰 Profit: {_format_idr(profit)} ({status})")

        if show_detail:
            recents = _recent_transactions(rows, 5)
            for d in recents:
                lines.append(_format_evidence_line(d))

    return "\n".join(lines)


def _handle_project_list_query(norm_text: str, days: int, period_label: str) -> str:
    """Handle queries listing all projects with summaries."""
    summary = get_summary(days) if days is not None else get_summary(365)
    by_projek = summary.get("by_projek", {})

    if not by_projek:
        return f"Tidak ada data projek ({period_label})."

    lines = [
        f"📊 Daftar Projek ({period_label})",
        f"📋 {len(by_projek)} projek aktif",
    ]

    sorted_projects = sorted(
        by_projek.values(),
        key=lambda x: (x.get("expense", 0) + x.get("income", 0)),
        reverse=True
    )

    for i, info in enumerate(sorted_projects, 1):
        name = info.get("name", "?")
        inc = info.get("income", 0)
        exp = info.get("expense", 0)
        profit = inc - exp
        status = "✅" if profit > 0 else "❌" if profit < 0 else "➖"
        lines.append(f"\n{i}. {name}")
        lines.append(f"   📥 {_format_idr(inc)} | 📤 {_format_idr(exp)} | {status} {_format_idr(profit)}")

    return "\n".join(lines)


def _handle_general_query(norm_text: str, days: int, period_label: str, raw_query: str = "") -> str:
    wants_balance = any(k in norm_text for k in ["saldo", "balance", "sisa"])
    wants_income = any(k in norm_text for k in ["pemasukan", "income", "masuk"])
    wants_expense = any(k in norm_text for k in ["pengeluaran", "expense", "keluar", "biaya"])
    show_detail = _wants_detail(norm_text)

    descriptor_tokens = _extract_query_descriptor_tokens(raw_query or norm_text)
    scoped_rows = []
    scoped_applied = False

    if descriptor_tokens:
        data = get_all_data(days) if days is not None else get_all_data(None)
        filtered, scope_mode = _filter_rows_by_descriptors(data, descriptor_tokens)
        if scope_mode in {"strict", "loose"}:
            scoped_rows = filtered
            scoped_applied = True

    if scoped_applied:
        total_income = sum(d.get("jumlah", 0) for d in scoped_rows if d.get("tipe") == "Pemasukan")
        total_expense = sum(d.get("jumlah", 0) for d in scoped_rows if d.get("tipe") == "Pengeluaran")
        saldo = total_income - total_expense
    else:
        summary = get_summary(days) if days is not None else get_summary(365)
        total_income = summary.get("total_pemasukan", 0)
        total_expense = summary.get("total_pengeluaran", 0)
        saldo = summary.get("saldo", 0)

    lines = []

    if scoped_applied:
        lines.append(f"🔍 Filter: {', '.join(descriptor_tokens)}")
        lines.append(f"📋 {len(scoped_rows)} transaksi cocok ({period_label})")

    if wants_income and not wants_expense:
        lines.append(f"\n📥 Total pemasukan: {_format_idr(total_income)}")
    elif wants_expense and not wants_income:
        lines.append(f"\n📤 Total pengeluaran: {_format_idr(total_expense)}")
    elif wants_balance:
        lines.append(f"\n💰 Saldo: {_format_idr(saldo)}")
    else:
        if not lines:
            lines.append(f"📊 Ringkasan Keuangan ({period_label})")
        lines.append(f"\n📥 Pemasukan: {_format_idr(total_income)}")
        lines.append(f"📤 Pengeluaran: {_format_idr(total_expense)}")
        lines.append(f"💰 Saldo: {_format_idr(saldo)}")

    # Show evidence when filtered or detail requested
    if scoped_applied or show_detail:
        limit = _evidence_limit(norm_text)
        source = scoped_rows if scoped_applied else (get_all_data(days) if days is not None else get_all_data(None))
        title = "📝 Transaksi yang cocok:" if scoped_applied else "📝 Transaksi terakhir:"
        _append_evidence(lines, source, limit, title)

    return "\n".join(lines)


# ===================== PHASE 3: ROBUST HANDLERS =====================

def _handle_ranking_query(norm_text: str, days: int, period_label: str) -> str:
    """Handle ranking questions: projek paling untung/rugi, dompet paling aktif."""
    wants_profit = any(k in norm_text for k in ["untung", "profit", "laba"])
    wants_loss = any(k in norm_text for k in ["rugi", "loss", "buntung", "boros"])
    wants_dompet = any(k in norm_text for k in ["dompet", "wallet"])
    wants_active = any(k in norm_text for k in ["aktif", "ramai", "banyak"])

    if wants_dompet:
        # Cross-dompet ranking
        data = get_all_data(days) if days is not None else get_all_data(None)
        by_dompet = {}
        for d in data:
            comp = d.get("company_sheet", "Unknown")
            if comp not in by_dompet:
                by_dompet[comp] = {"income": 0, "expense": 0, "count": 0}
            by_dompet[comp]["count"] += 1
            if d.get("tipe") == "Pemasukan":
                by_dompet[comp]["income"] += d.get("jumlah", 0)
            else:
                by_dompet[comp]["expense"] += d.get("jumlah", 0)

        if not by_dompet:
            return f"Belum ada data transaksi ({period_label})."

        if wants_active:
            sorted_d = sorted(by_dompet.items(), key=lambda x: x[1]["count"], reverse=True)
        elif wants_loss:
            sorted_d = sorted(by_dompet.items(), key=lambda x: x[1]["expense"], reverse=True)
        else:
            sorted_d = sorted(by_dompet.items(), key=lambda x: x[1]["income"], reverse=True)

        lines = [f"🏆 Ranking Dompet ({period_label})"]
        for i, (name, info) in enumerate(sorted_d, 1):
            lines.append(
                f"\n{i}. {name}"
                f"\n   📥 {_format_idr(info['income'])} | 📤 {_format_idr(info['expense'])} | 📋 {info['count']} tx"
            )
        return "\n".join(lines)

    # Project ranking
    summary = get_summary(days) if days is not None else get_summary(365)
    by_projek = summary.get("by_projek", {})

    if not by_projek:
        return f"Belum ada data projek ({period_label})."

    if wants_loss:
        sorted_p = sorted(by_projek.values(), key=lambda x: x.get("profit_loss", 0))
    elif wants_profit:
        sorted_p = sorted(by_projek.values(), key=lambda x: x.get("profit_loss", 0), reverse=True)
    else:
        sorted_p = sorted(by_projek.values(), key=lambda x: x.get("expense", 0) + x.get("income", 0), reverse=True)

    title = "paling untung" if wants_profit else "paling rugi" if wants_loss else "terbesar"
    lines = [f"🏆 Ranking Projek {title} ({period_label})"]
    for i, info in enumerate(sorted_p[:10], 1):
        name = info.get("name", "?")
        inc = info.get("income", 0)
        exp = info.get("expense", 0)
        pl = info.get("profit_loss", inc - exp)
        status = "✅" if pl > 0 else "❌" if pl < 0 else "➖"
        lines.append(
            f"\n{i}. {name}"
            f"\n   📥 {_format_idr(inc)} | 📤 {_format_idr(exp)} | {status} {_format_idr(pl)}"
        )
    return "\n".join(lines)


def _handle_category_query(norm_text: str, days: int, period_label: str) -> str:
    """Handle category-specific queries: total gaji, total material, dll."""
    data = get_all_data(days) if days is not None else get_all_data(None)
    if not data:
        return f"Belum ada data transaksi ({period_label})."

    # Map common keywords to category names
    category_mappings = {
        "gaji": ["Gaji"],
        "upah": ["Gaji"],
        "tukang": ["Gaji"],
        "honor": ["Gaji"],
        "borongan": ["Gaji"],
        "bahan": ["Bahan Alat"],
        "alat": ["Bahan Alat"],
        "material": ["Bahan Alat"],
        "semen": ["Bahan Alat"],
        "operasi": ["Operasi Kantor"],
        "listrik": ["Operasi Kantor"],
        "internet": ["Operasi Kantor"],
        "transport": ["Lain-lain"],
        "bensin": ["Lain-lain"],
        "makan": ["Lain-lain"],
    }

    target_categories = set()
    target_keyword = ""
    for keyword, cats in category_mappings.items():
        if keyword in norm_text:
            target_categories.update(cats)
            target_keyword = keyword

    if not target_categories:
        # Show all categories
        summary = get_summary(days) if days is not None else get_summary(365)
        by_kat = summary.get("by_kategori", {})
        if not by_kat:
            return f"Belum ada data pengeluaran per kategori ({period_label})."

        lines = [f"📂 Pengeluaran per Kategori ({period_label})"]
        for kat, amt in sorted(by_kat.items(), key=lambda x: -x[1]):
            lines.append(f"  • {kat}: {_format_idr(amt)}")
        total = sum(by_kat.values())
        lines.append(f"\n📊 Total: {_format_idr(total)}")
        return "\n".join(lines)

    # Filter by target categories
    cat_rows = [
        d for d in data
        if d.get("kategori") in target_categories and d.get("tipe") == "Pengeluaran"
    ]
    if not cat_rows:
        return f"Tidak ada pengeluaran kategori {target_keyword} ({period_label})."

    total = sum(d.get("jumlah", 0) for d in cat_rows)
    show_detail = _wants_detail(norm_text)

    lines = [
        f"📂 Pengeluaran {', '.join(target_categories)} ({period_label})",
        f"📤 Total: {_format_idr(total)}",
        f"📋 {len(cat_rows)} transaksi",
    ]

    limit = _evidence_limit(norm_text)
    _append_evidence(lines, cat_rows, limit, "📝 Transaksi:")

    return "\n".join(lines)


def _handle_minmax_query(norm_text: str, days: int, period_label: str) -> str:
    """Handle min/max queries: transaksi terbesar, terkecil."""
    wants_max = any(k in norm_text for k in ["terbesar", "tertinggi", "termahal", "paling besar", "paling mahal"])
    wants_min = any(k in norm_text for k in ["terkecil", "terendah", "termurah", "paling kecil", "paling murah"])

    data = get_all_data(days) if days is not None else get_all_data(None)
    if not data:
        return f"Belum ada data transaksi ({period_label})."

    # Filter by type if specified
    wants_expense = any(k in norm_text for k in ["pengeluaran", "expense", "keluar"])
    wants_income = any(k in norm_text for k in ["pemasukan", "income", "masuk"])

    if wants_expense:
        filtered = [d for d in data if d.get("tipe") == "Pengeluaran"]
        type_label = "Pengeluaran"
    elif wants_income:
        filtered = [d for d in data if d.get("tipe") == "Pemasukan"]
        type_label = "Pemasukan"
    else:
        filtered = data
        type_label = "Transaksi"

    if not filtered:
        return f"Tidak ada data {type_label.lower()} ({period_label})."

    if wants_min:
        sorted_data = sorted(filtered, key=lambda d: d.get("jumlah", 0))
        title = f"📉 {type_label} Terkecil ({period_label})"
    else:
        sorted_data = sorted(filtered, key=lambda d: d.get("jumlah", 0), reverse=True)
        title = f"📈 {type_label} Terbesar ({period_label})"

    limit = _evidence_limit(norm_text)
    top = sorted_data[:limit]

    lines = [title]
    for i, d in enumerate(top, 1):
        lines.append(_format_evidence_line(d))

    return "\n".join(lines)


def _handle_cross_dompet_query(norm_text: str, days: int, period_label: str) -> str:
    """Handle cross-dompet comparison queries."""
    data = get_all_data(days) if days is not None else get_all_data(None)
    if not data:
        return f"Belum ada data transaksi ({period_label})."

    by_dompet = {}
    for d in data:
        comp = d.get("company_sheet", "Unknown")
        if comp not in by_dompet:
            by_dompet[comp] = {"income": 0, "expense": 0, "count": 0}
        by_dompet[comp]["count"] += 1
        if d.get("tipe") == "Pemasukan":
            by_dompet[comp]["income"] += d.get("jumlah", 0)
        else:
            by_dompet[comp]["expense"] += d.get("jumlah", 0)

    if not by_dompet:
        return f"Belum ada data dompet ({period_label})."

    # Also get current balances
    balances = get_wallet_balances()

    lines = [f"💼 Perbandingan Dompet ({period_label})"]
    for comp, info in sorted(by_dompet.items(), key=lambda x: -(x[1]["income"] + x[1]["expense"])):
        net = info["income"] - info["expense"]
        bal_info = balances.get(comp, {})
        saldo = bal_info.get("saldo", None)

        lines.append(f"\n{'─' * 28}")
        lines.append(f"💼 {comp}")
        if saldo is not None:
            lines.append(f"   💰 Saldo: {_format_idr(saldo)}")
        lines.append(f"   📥 Masuk: {_format_idr(info['income'])}")
        lines.append(f"   📤 Keluar: {_format_idr(info['expense'])}")
        lines.append(f"   📋 {info['count']} transaksi")

    return "\n".join(lines)


def _handle_person_query(query: str, norm_text: str, days: int, period_label: str) -> str:
    """Handle per-person queries: total bayar ke sugeng, fee azen, dll."""
    # Extract person name from query — remove stopwords and look for remaining tokens
    descriptor_tokens = _extract_query_descriptor_tokens(query)
    if not descriptor_tokens:
        return _handle_general_query(norm_text, days, period_label, query)

    data = get_all_data(days) if days is not None else get_all_data(None)
    if not data:
        return f"Belum ada data transaksi ({period_label})."

    filtered, scope_mode = _filter_rows_by_descriptors(data, descriptor_tokens)
    if scope_mode == "none" or len(filtered) == len(data):
        return _handle_general_query(norm_text, days, period_label, query)

    income = sum(d.get("jumlah", 0) for d in filtered if d.get("tipe") == "Pemasukan")
    expense = sum(d.get("jumlah", 0) for d in filtered if d.get("tipe") == "Pengeluaran")

    # Group by project for breakdown
    by_proj = {}
    for d in filtered:
        proj = d.get("nama_projek", "Tanpa Projek") or "Tanpa Projek"
        if proj not in by_proj:
            by_proj[proj] = {"income": 0, "expense": 0, "count": 0}
        by_proj[proj]["count"] += 1
        if d.get("tipe") == "Pemasukan":
            by_proj[proj]["income"] += d.get("jumlah", 0)
        else:
            by_proj[proj]["expense"] += d.get("jumlah", 0)

    filter_label = ', '.join(descriptor_tokens)
    lines = [
        f"🔍 Pencarian: \"{filter_label}\" ({period_label})",
        f"📋 {len(filtered)} transaksi ditemukan",
    ]

    if expense > 0:
        lines.append(f"\n📤 Total pengeluaran: {_format_idr(expense)}")
    if income > 0:
        lines.append(f"📥 Total pemasukan: {_format_idr(income)}")

    # Show per-project breakdown if multiple projects
    if len(by_proj) > 1:
        lines.append("\n📊 Per projek:")
        for proj, info in sorted(by_proj.items(), key=lambda x: -(x[1]["expense"] + x[1]["income"])):
            exp_str = f"📤 {_format_idr(info['expense'])}" if info["expense"] else ""
            inc_str = f"📥 {_format_idr(info['income'])}" if info["income"] else ""
            amounts = " | ".join(filter(None, [exp_str, inc_str]))
            lines.append(f"  • {proj}: {amounts} ({info['count']} tx)")

    # Evidence
    limit = _evidence_limit(norm_text)
    _append_evidence(lines, filtered, limit, "\n📝 Rincian transaksi:")

    return "\n".join(lines)


def _fallback_ai(query: str, days: int) -> str:
    try:
        context_days = days if days is not None else 90
        formatted_context = format_data_for_ai(days=context_days)
        if not formatted_context or "Tidak ada data transaksi" in formatted_context:
            return "Belum ada data transaksi yang cukup untuk dianalisis."

        ctx = _strip_context_tags(formatted_context)
        system_prompt = (
            "Anda asisten keuangan perusahaan jasa. "
            "Jawab dengan bahasa Indonesia yang natural, rinci, dan spesifik. "
            "Selalu sebutkan rincian transaksi yang relevan (tanggal, jumlah, keterangan). "
            "Format angka dalam Rupiah (Rp X.XXX.XXX). "
            "Jangan menyebut tag atau section data. "
            "Jika data tidak ada, katakan dengan jelas. "
            "Gunakan emoji untuk membuat respon lebih mudah dibaca."
        )
        user_prompt = f"Pertanyaan: {query}\n\nDATA:\n{ctx}\n\nJawab secara langsung dengan rincian."

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1024,
        )

        answer = response.choices[0].message.content.strip()
        return answer
    except Exception as e:
        logger.error(f"AI fallback failed: {e}", exc_info=True)
        return "Maaf, terjadi kesalahan saat menganalisis data."


# ===================== MAIN ENTRY POINT =====================

def handle_query_command(query: str, user_id: str, chat_id: str, raw_query: str = None) -> str:
    try:
        clean_query = sanitize_input(query)
        if not clean_query:
            return "Pertanyaan tidak valid."

        raw_clean = sanitize_input(raw_query) if raw_query else None
        is_injection, _ = detect_prompt_injection(clean_query)
        if is_injection:
            return "Pertanyaan tidak valid. Mohon tanya tentang data keuangan."

        detect_query = raw_clean or clean_query
        norm = normalize_nyeleneh_text(detect_query)
        raw_norm = _normalize_text(detect_query)
        days, period_label = _extract_days(norm)

        dompet = resolve_dompet_from_text(raw_norm)
        wants_hutang = any(k in norm for k in ["hutang", "utang", "piutang"])
        wants_operational = any(k in norm for k in ["operasional", "kantor", "overhead"])
        has_project_keyword = any(k in norm for k in ["projek", "project", "proyek"])
        wants_project = has_project_keyword or bool(
            extract_project_name_from_text(detect_query)
        )
        wants_finished = any(k in norm for k in ["finish", "selesai", "kelar"]) and (
            has_project_keyword or "projek" in norm or "project" in norm
        )
        wants_project_list = any(k in norm for k in ["daftar", "list", "semua"]) and has_project_keyword

        # Phase 3: New query type detection
        wants_ranking = any(k in norm for k in ["ranking", "peringkat", "paling", "terbanyak"])
        wants_category = any(k in norm for k in [
            "kategori", "gaji", "upah", "tukang", "bahan", "alat", "material",
            "semen", "listrik", "internet", "transport", "bensin", "makan",
            "honor", "borongan",
        ])
        wants_minmax = any(k in norm for k in [
            "terbesar", "tertinggi", "termahal", "terkecil", "terendah", "termurah",
            "paling besar", "paling kecil", "paling mahal", "paling murah",
        ])
        wants_comparison = any(k in norm for k in [
            "bandingkan", "perbandingan", "compare", "banding"
        ]) and any(k in norm for k in ["dompet", "wallet"])

        # ============ ROUTING (priority order) ============

        # 1. Finished projects
        if wants_finished:
            return _handle_finished_projects_query(norm, days, period_label)

        # 2. Project list
        if wants_project_list:
            return _handle_project_list_query(norm, days, period_label)

        # 3. Ranking (projek paling untung, dompet paling aktif)
        if wants_ranking:
            return _handle_ranking_query(norm, days, period_label)

        # 4. Min/max (transaksi terbesar/terkecil)
        if wants_minmax:
            return _handle_minmax_query(norm, days, period_label)

        # 5. Cross-dompet comparison
        if wants_comparison:
            return _handle_cross_dompet_query(norm, days, period_label)

        # 6. Project-specific query
        if wants_project and has_project_keyword:
            return _handle_project_query(detect_query, norm, days, period_label)

        # 7. Hutang/debt
        if wants_hutang:
            return _handle_hutang_query(norm, days, period_label, dompet)

        # 8. Wallet/dompet query
        if dompet:
            return _handle_wallet_query(dompet, norm, days, period_label, detect_query)

        # 9. Operational
        if wants_operational:
            return _handle_operational_query(norm, days, period_label)

        # 10. Category-specific (gaji, bahan, transport)
        if wants_category:
            return _handle_category_query(norm, days, period_label)

        # 11. Project without explicit keyword (detected by name)
        if wants_project:
            return _handle_project_query(detect_query, norm, days, period_label)

        # 12. Check if this looks like a person/descriptor search
        desc_tokens = _extract_query_descriptor_tokens(detect_query)
        if desc_tokens:
            return _handle_person_query(detect_query, norm, days, period_label)

        # 13. General summary
        result = _handle_general_query(norm, days, period_label, detect_query)

        # 14. If general query returns very little info, try AI fallback
        if result and len(result) > 30:
            return result

        return _fallback_ai(detect_query, days)

    except Exception as e:
        logger.error(f"Query handler failed: {e}", exc_info=True)
        return _fallback_ai(query, DEFAULT_DAYS)
