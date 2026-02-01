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
    get_summary,
    get_wallet_balances,
)
from utils.normalizer import normalize_nyeleneh_text
from utils.parsers import extract_project_name_from_text

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 30


def _format_idr(amount: int) -> str:
    try:
        return f"Rp {int(amount):,}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split()).casefold()


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

    for info in by_projek.values():
        name = info.get("name", "")
        if name and _normalize_text(name) in query_norm:
            return info, 1.0

    candidate = extract_project_name_from_text(query) or ""
    candidate_norm = _normalize_text(candidate)

    best = None
    best_score = 0.0
    for info in by_projek.values():
        name = info.get("name", "")
        name_norm = _normalize_text(name)
        if not name_norm:
            continue
        if candidate_norm and (candidate_norm in name_norm or name_norm in candidate_norm):
            score = 0.95
        else:
            score = SequenceMatcher(None, candidate_norm or query_norm, name_norm).ratio()
        if score > best_score:
            best = info
            best_score = score

    if best_score >= 0.6:
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
    income = match.get("income", 0)
    expense = match.get("expense", 0)
    profit = match.get("profit_loss", 0)
    status = "UNTUNG" if profit > 0 else "RUGI" if profit < 0 else "NETRAL"

    data = get_all_data(days) if days is not None else get_all_data(None)
    project_rows = [
        d for d in data
        if _normalize_text(d.get("nama_projek", "")) == _normalize_text(project_name)
        or _normalize_text(project_name) in _normalize_text(d.get("nama_projek", ""))
    ]
    dompet_hint = _project_dompet_hint(project_rows)
    dompet_txt = f" | Dompet: {dompet_hint}" if dompet_hint else ""

    lines = [f"Projek {project_name} ({period_label}){dompet_txt}"]

    if wants_income and not wants_expense:
        lines.append(f"Pemasukan: {_format_idr(income)}")
    elif wants_expense and not wants_income:
        lines.append(f"Pengeluaran: {_format_idr(expense)}")
    else:
        lines.append(f"Pemasukan: {_format_idr(income)} | Pengeluaran: {_format_idr(expense)}")

    if wants_profit or (not wants_income and not wants_expense):
        lines.append(f"Laba/Rugi: {_format_idr(profit)} ({status})")

    if wants_detail and project_rows:
        recents = _recent_transactions(project_rows, 3)
        if recents:
            lines.append("Transaksi terakhir:")
            for d in recents:
                amt = _format_idr(d.get("jumlah", 0))
                lines.append(f"- {d.get('tanggal','')} {d.get('tipe','')} {amt} | {d.get('keterangan','')}")

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


def handle_query_command(query: str, user_id: str, chat_id: str) -> str:
    try:
        clean_query = sanitize_input(query)
        if not clean_query:
            return "Pertanyaan tidak valid."

        is_injection, _ = detect_prompt_injection(clean_query)
        if is_injection:
            return "Pertanyaan tidak valid. Mohon tanya tentang data keuangan."

        norm = normalize_nyeleneh_text(clean_query)
        days, period_label = _extract_days(norm)

        dompet = resolve_dompet_from_text(norm)
        wants_operational = any(k in norm for k in ["operasional", "kantor", "overhead"])
        wants_project = any(k in norm for k in ["projek", "project", "proyek"]) or bool(
            extract_project_name_from_text(clean_query)
        )

        if dompet:
            return _handle_wallet_query(dompet, norm, days, period_label)

        if wants_operational:
            return _handle_operational_query(norm, days, period_label)

        if wants_project:
            return _handle_project_query(clean_query, norm, days, period_label)

        return _handle_general_query(norm, days, period_label)

    except Exception as e:
        logger.error(f"Query handler failed: {e}", exc_info=True)
        return _fallback_ai(query, DEFAULT_DAYS)
