"""
Smart Query Handler - Hybrid (Rules + Data + AI fallback)
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

PROJECT_PREFIX_RE = re.compile(r"^\s*(holla|hojja)\s*[-:]\s*", re.IGNORECASE)
PROJECT_PHASE_RE = re.compile(r"\s*\((start|finish)\)\s*$", re.IGNORECASE)
PROJECT_QUERY_STOPWORDS = {
    "bot", "tolong", "dong", "berapa", "gimana", "bagaimana", "cek", "check", "lihat",
    "pengeluaran", "pemasukan", "income", "expense", "biaya", "total", "rekap", "status",
    "projek", "project", "proyek", "projectnya", "projeknya", "hari", "ini", "kemarin",
    "minggu", "bulan", "tahun", "terakhir", "detail", "rinci", "transaksi", "laporan", "berapa?",
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


def _extract_query_descriptor_tokens(query: str, project_name: str = "") -> list:
    """Get descriptive tokens from query (e.g., 'fee', 'sugeng') excluding boilerplate words."""
    query_tokens = re.findall(r"[a-zA-Z0-9]{3,}", _normalize_text(query))
    project_tokens = set(re.findall(r"[a-zA-Z0-9]{3,}", _normalize_project_label(project_name)))

    tokens = []
    for token in query_tokens:
        if token in PROJECT_QUERY_STOPWORDS:
            continue
        if token in project_tokens:
            continue
        tokens.append(token)
    return sorted(set(tokens))


def _parse_date(date_str: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue
    return datetime.min


def _extract_days(text: str) -> tuple:
    text = text or ""

    if any(k in text for k in ["sejak awal", "semua", "all time", "alltime"]):
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


def _handle_wallet_query(dompet: str, norm_text: str, days: int, period_label: str) -> str:
    wants_balance = any(k in norm_text for k in ["saldo", "balance", "sisa"])
    wants_income = any(k in norm_text for k in ["pemasukan", "income", "masuk"])
    wants_expense = any(k in norm_text for k in ["pengeluaran", "expense", "keluar", "biaya"])
    wants_detail = any(k in norm_text for k in ["detail", "rinci", "transaksi", "terakhir", "riwayat", "list"])

    if wants_balance and not (wants_income or wants_expense):
        balances = get_wallet_balances()
        info = balances.get(dompet)
        if not info:
            return f"Dompet {dompet} tidak ditemukan."
        lines = [
            f"Saldo dompet {dompet} saat ini: {_format_idr(info.get('saldo', 0))}.",
            f"Masuk: {_format_idr(info.get('pemasukan', 0))} | Keluar: {_format_idr(info.get('pengeluaran', 0))}",
        ]
        op_debit = info.get("operational_debit", 0)
        if op_debit:
            lines.append(f"Potongan operasional: {_format_idr(op_debit)}")
        return "\n".join(lines)

    data = get_all_data(days) if days is not None else get_all_data(None)
    dompet_data = [d for d in data if d.get("company_sheet") == dompet]

    if not dompet_data:
        return f"Belum ada transaksi untuk dompet {dompet} ({period_label})."

    income = sum(d["jumlah"] for d in dompet_data if d.get("tipe") == "Pemasukan")
    expense = sum(d["jumlah"] for d in dompet_data if d.get("tipe") == "Pengeluaran")
    net = income - expense

    if wants_income and not wants_expense:
        lines = [f"Pemasukan dompet {dompet} ({period_label}): {_format_idr(income)}."]
    elif wants_expense and not wants_income:
        lines = [f"Pengeluaran dompet {dompet} ({period_label}): {_format_idr(expense)}."]
    else:
        lines = [
            f"Ringkas dompet {dompet} ({period_label}):",
            f"Pemasukan: {_format_idr(income)} | Pengeluaran: {_format_idr(expense)} | Net: {_format_idr(net)}",
        ]

    if wants_detail:
        recents = _recent_transactions(dompet_data, 3)
        if recents:
            lines.append("Transaksi terakhir:")
            for d in recents:
                amt = _format_idr(d.get("jumlah", 0))
                proj = d.get("nama_projek", "")
                proj_txt = f" ({proj})" if proj else ""
                lines.append(f"- {d.get('tanggal','')} {d.get('tipe','')} {amt} | {d.get('keterangan','')}{proj_txt}")

    return "\n".join(lines)


def _handle_operational_query(norm_text: str, days: int, period_label: str) -> str:
    data = get_all_data(days) if days is not None else get_all_data(None)
    ops = [d for d in data if d.get("company_sheet") == OPERASIONAL_SHEET_NAME]
    if not ops:
        return f"Belum ada data operasional ({period_label})."

    total = sum(d["jumlah"] for d in ops if d.get("tipe") == "Pengeluaran")
    wants_detail = any(k in norm_text for k in ["detail", "rinci", "transaksi", "terakhir", "riwayat", "list"])

    lines = [f"Total operasional ({period_label}): {_format_idr(total)}."]
    if wants_detail:
        recents = _recent_transactions(ops, 3)
        if recents:
            lines.append("Transaksi operasional terakhir:")
            for d in recents:
                amt = _format_idr(d.get("jumlah", 0))
                lines.append(f"- {d.get('tanggal','')} {amt} | {d.get('keterangan','')}")

    return "\n".join(lines)


def _handle_hutang_query(norm_text: str, days: int, period_label: str, dompet: str = None) -> str:
    # days is not strictly applied for OPEN entries, but keep period label for consistency.
    if dompet:
        open_as_borrower = find_open_hutang(yang_hutang=dompet)
        open_as_lender = find_open_hutang(yang_dihutangi=dompet)

        borrower_total = sum(int(row.get("jumlah", 0) or 0) for row in open_as_borrower)
        lender_total = sum(int(row.get("jumlah", 0) or 0) for row in open_as_lender)
        net = lender_total - borrower_total

        lines = [
            f"Status utang dompet {dompet} ({period_label}):",
            f"- Masih berutang (sebagai peminjam): {_format_idr(borrower_total)} ({len(open_as_borrower)} transaksi)",
            f"- Piutang belum lunas (sebagai pemberi): {_format_idr(lender_total)} ({len(open_as_lender)} transaksi)",
            f"- Posisi bersih utang/piutang: {_format_idr(net)}",
        ]
        return "\n".join(lines)

    summary = get_hutang_summary(days=days or 0)
    lines = [f"Ringkas utang antar dompet ({period_label}):"]
    lines.append(
        f"OPEN: {_format_idr(summary.get('open_total', 0))} ({summary.get('open_count', 0)} transaksi)"
    )
    lines.append(
        f"PAID: {_format_idr(summary.get('paid_total', 0))} ({summary.get('paid_count', 0)} transaksi)"
    )
    lines.append(
        f"CANCELLED: {_format_idr(summary.get('cancelled_total', 0))} ({summary.get('cancelled_count', 0)} transaksi)"
    )
    return "\n".join(lines)


def _handle_project_query(query: str, norm_text: str, days: int, period_label: str) -> str:
    wants_profit = any(k in norm_text for k in ["untung", "rugi", "laba", "profit"])
    wants_income = any(k in norm_text for k in ["pemasukan", "income", "masuk"])
    wants_expense = any(k in norm_text for k in ["pengeluaran", "expense", "keluar", "biaya"])
    wants_detail = any(k in norm_text for k in ["detail", "rinci", "transaksi", "terakhir", "riwayat", "list"])

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

    # If query has descriptor words (e.g. fee/sugeng), filter by keterangan for better specificity.
    descriptor_tokens = _extract_query_descriptor_tokens(query, project_name)
    filtered_rows = project_rows
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

    income = sum(d.get("jumlah", 0) for d in filtered_rows if d.get("tipe") == "Pemasukan")
    expense = sum(d.get("jumlah", 0) for d in filtered_rows if d.get("tipe") == "Pengeluaran")
    profit = income - expense
    status = "UNTUNG" if profit > 0 else "RUGI" if profit < 0 else "NETRAL"

    dompet_hint = _project_dompet_hint(filtered_rows or project_rows)
    dompet_txt = f" | Dompet: {dompet_hint}" if dompet_hint else ""

    lines = [f"Projek {project_name} ({period_label}){dompet_txt}"]

    if descriptor_tokens and filtered_rows is not project_rows:
        lines.append(f"Filter deskripsi: {', '.join(descriptor_tokens)}")

    if wants_income and not wants_expense:
        lines.append(f"Pemasukan: {_format_idr(income)}")
    elif wants_expense and not wants_income:
        lines.append(f"Pengeluaran: {_format_idr(expense)}")
    else:
        lines.append(f"Pemasukan: {_format_idr(income)} | Pengeluaran: {_format_idr(expense)}")

    if wants_profit or (not wants_income and not wants_expense):
        lines.append(f"Laba/Rugi: {_format_idr(profit)} ({status})")

    if wants_detail and filtered_rows:
        recents = _recent_transactions(filtered_rows, 3)
        if recents:
            title = "Transaksi yang dihitung:" if is_scoped_by_descriptor else "Transaksi terakhir:"
            lines.append(title)
            for d in recents:
                amt = _format_idr(d.get("jumlah", 0))
                ket = (d.get("keterangan", "") or "").strip()
                ket = ket[:90] + "..." if len(ket) > 93 else ket
                lines.append(f"- {d.get('tanggal','')} {d.get('tipe','')} {amt} | {ket}")
            if is_scoped_by_descriptor and len(filtered_rows) > show_limit:
                lines.append(f"... {len(filtered_rows) - show_limit} transaksi lain sesuai filter")

    return "\n".join(lines)


def _handle_general_query(norm_text: str, days: int, period_label: str) -> str:
    wants_balance = any(k in norm_text for k in ["saldo", "balance", "sisa"])
    wants_income = any(k in norm_text for k in ["pemasukan", "income", "masuk"])
    wants_expense = any(k in norm_text for k in ["pengeluaran", "expense", "keluar", "biaya"])
    wants_detail = any(k in norm_text for k in ["detail", "rinci", "transaksi", "terakhir", "riwayat", "list"])

    summary = get_summary(days) if days is not None else get_summary(365)

    total_income = summary.get("total_pemasukan", 0)
    total_expense = summary.get("total_pengeluaran", 0)
    saldo = summary.get("saldo", 0)

    if wants_income and not wants_expense:
        lines = [f"Total pemasukan ({period_label}): {_format_idr(total_income)}."]
    elif wants_expense and not wants_income:
        lines = [f"Total pengeluaran ({period_label}): {_format_idr(total_expense)}."]
    elif wants_balance:
        lines = [f"Saldo ({period_label}): {_format_idr(saldo)}."]
    else:
        lines = [
            f"Ringkas keuangan ({period_label}):",
            f"Pemasukan: {_format_idr(total_income)} | Pengeluaran: {_format_idr(total_expense)} | Saldo: {_format_idr(saldo)}",
        ]

    if wants_detail:
        data = get_all_data(days) if days is not None else get_all_data(None)
        recents = _recent_transactions(data, 5)
        if recents:
            lines.append("Transaksi terakhir:")
            for d in recents:
                amt = _format_idr(d.get("jumlah", 0))
                proj = d.get("nama_projek", "")
                proj_txt = f" ({proj})" if proj else ""
                lines.append(f"- {d.get('tanggal','')} {d.get('tipe','')} {amt} | {d.get('keterangan','')}{proj_txt}")

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
            "Jawab dengan bahasa Indonesia yang natural, ringkas, dan spesifik. "
            "Jangan menyebut tag atau section data. "
            "Jika data tidak ada, katakan dengan jelas."
        )
        user_prompt = f"Pertanyaan: {query}\n\nDATA:\n{ctx}\n\nJawab secara langsung."

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=512,
        )

        answer = response.choices[0].message.content.strip()
        return answer
    except Exception as e:
        logger.error(f"AI fallback failed: {e}", exc_info=True)
        return "Maaf, terjadi kesalahan saat menganalisis data."


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

        # Prioritize explicit project questions over dompet alias collisions
        # e.g. "pengeluaran projek Vadim Bali" should be project scope, not dompet TX BALI.
        if wants_project and has_project_keyword:
            return _handle_project_query(detect_query, norm, days, period_label)

        if wants_hutang:
            return _handle_hutang_query(norm, days, period_label, dompet)

        if dompet:
            return _handle_wallet_query(dompet, norm, days, period_label)

        if wants_operational:
            return _handle_operational_query(norm, days, period_label)

        if wants_project:
            return _handle_project_query(detect_query, norm, days, period_label)

        return _handle_general_query(norm, days, period_label)

    except Exception as e:
        logger.error(f"Query handler failed: {e}", exc_info=True)
        return _fallback_ai(query, DEFAULT_DAYS)
