"""
row_validator.py - Validasi baris saat baca (Fase 1-kecil, pagar data)

TUJUAN
------
Mendeteksi baris yang kemungkinan hasil EDIT MANUAL berantakan di Google
Sheets, supaya bot bisa MEMPERINGATKAN, bukan diam-diam salah hitung.

Sifat modul ini:
- PURE: hanya memeriksa list-of-dict yang sudah dibaca (mis. dari
  get_raw_rows_for_audit). Tidak menyentuh Sheets / jaringan / cache.
- KONSERVATIF: hanya menandai yang JELAS janggal, supaya tidak banyak alarm palsu.
- READ-ONLY: tidak mengubah data, hanya melaporkan temuan.

Dipakai untuk fitur "/audit" / warning di laporan. Tidak mengubah logika tulis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from config.wallets import DOMPET_COMPANIES, DOMPET_SHEETS

VALID_TIPE = {"Pemasukan", "Pengeluaran"}

# Sumber kebenaran nama dompet/company yang dikenal bot.
# company_sheet pada data audit berisi nama company/dompet, atau
# "Operasional Kantor" untuk biaya operasional.
_KNOWN_COMPANY_NAMES = {
    name.strip().lower()
    for names in DOMPET_COMPANIES.values()
    for name in names
}
_KNOWN_SHEET_NAMES = {s.strip().lower() for s in DOMPET_SHEETS}
_OPERATIONAL_LABELS = {"operasional kantor", "operasional", "operational"}


@dataclass
class RowIssue:
    """Satu temuan janggal pada satu baris."""

    index: int                      # posisi baris di list data (0-based)
    field: str                      # field bermasalah: tanggal/jumlah/tipe/dompet
    problem: str                    # kode masalah singkat
    value: Any = None               # nilai mentah yang bermasalah
    keterangan: str = ""            # konteks agar manusia mudah mengenali baris
    sheet_name: str = ""            # nama worksheet bila tersedia
    sheet_row: Optional[int] = None  # nomor row asli di worksheet bila tersedia

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "field": self.field,
            "problem": self.problem,
            "value": self.value,
            "keterangan": self.keterangan,
            "sheet_name": self.sheet_name,
            "sheet_row": self.sheet_row,
        }


def _parse_amount(value: Any) -> Optional[int]:
    if isinstance(value, bool):  # bool is subclass of int; reject explicitly
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    cleaned = re.sub(r"(?i)\b(rp|idr)\b", "", text)
    cleaned = cleaned.replace(" ", "")
    if not cleaned or cleaned.startswith("-"):
        return None
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", cleaned):
        return None

    last_dot = cleaned.rfind(".")
    last_comma = cleaned.rfind(",")
    last_sep = max(last_dot, last_comma)
    if last_sep != -1:
        suffix = cleaned[last_sep + 1:]
        has_mixed_separators = last_dot != -1 and last_comma != -1
        if len(suffix) <= 2 and (has_mixed_separators or len(suffix) != 3):
            cleaned = cleaned[:last_sep]

    digits = cleaned.replace(",", "").replace(".", "")
    try:
        return int(digits)
    except ValueError:
        return None


def _amount_is_valid(value: Any) -> bool:
    """jumlah harus angka bulat > 0; terima format Rupiah umum dari Sheet."""
    amount = _parse_amount(value)
    return amount is not None and amount > 0


def _date_is_valid(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    return False


def _dompet_label_is_known(row: Dict[str, Any]) -> bool:
    """Cek apakah baris terhubung ke dompet/company/operasional yang dikenal."""
    candidates = [
        row.get("company_sheet"),
        row.get("dompet"),
        row.get("sheet_name"),
    ]
    for raw in candidates:
        label = str(raw or "").strip().lower()
        if not label:
            continue
        if label in _OPERATIONAL_LABELS:
            return True
        if label in _KNOWN_COMPANY_NAMES:
            return True
        if label in _KNOWN_SHEET_NAMES:
            return True
    return False


def validate_row(row: Dict[str, Any], index: int = 0) -> List[RowIssue]:
    """Validasi satu baris transaksi hasil baca. Mengembalikan daftar temuan."""
    issues: List[RowIssue] = []
    if not isinstance(row, dict):
        issues.append(RowIssue(index=index, field="row", problem="not_a_dict", value=type(row).__name__))
        return issues

    ket = str(row.get("keterangan", "") or "")[:80]
    sheet_name = str(row.get("sheet_name", "") or "")
    try:
        sheet_row = int(row.get("sheet_row")) if row.get("sheet_row") is not None else None
    except (TypeError, ValueError):
        sheet_row = None

    def add_issue(field: str, problem: str, value: Any) -> None:
        issues.append(RowIssue(
            index=index,
            field=field,
            problem=problem,
            value=value,
            keterangan=ket,
            sheet_name=sheet_name,
            sheet_row=sheet_row,
        ))

    if not _date_is_valid(row.get("tanggal")):
        add_issue("tanggal", "invalid_or_missing_date", row.get("tanggal"))

    if not _amount_is_valid(row.get("jumlah")):
        add_issue("jumlah", "invalid_or_nonpositive_amount", row.get("jumlah"))

    tipe = str(row.get("tipe", "") or "").strip()
    if tipe not in VALID_TIPE:
        add_issue("tipe", "unknown_tipe", row.get("tipe"))

    if not _dompet_label_is_known(row):
        add_issue(
            "dompet",
            "unknown_dompet_or_company",
            row.get("company_sheet") or row.get("dompet") or row.get("sheet_name"),
        )

    return issues


def validate_rows(rows: List[Dict[str, Any]]) -> List[RowIssue]:
    """Validasi seluruh baris. Mengembalikan gabungan semua temuan."""
    issues: List[RowIssue] = []
    for i, row in enumerate(rows or []):
        issues.extend(validate_row(row, index=i))
    return issues


def summarize_issues(issues: List[RowIssue]) -> Dict[str, Any]:
    """Ringkasan temuan untuk laporan/log."""
    by_field: Dict[str, int] = {}
    for it in issues:
        by_field[it.field] = by_field.get(it.field, 0) + 1
    return {
        "total_issues": len(issues),
        "rows_flagged": len({it.index for it in issues}),
        "by_field": by_field,
    }


def _issue_location(issue: RowIssue) -> str:
    if issue.sheet_name and issue.sheet_row:
        return f"{issue.sheet_name} baris {issue.sheet_row}"
    return f"Baris {issue.index + 1}"


def format_issue_report(issues: List[RowIssue], max_lines: int = 10) -> str:
    """Format temuan jadi pesan WhatsApp yang ringkas dan ramah manusia."""
    if not issues:
        return "✅ Tidak ada baris janggal terdeteksi."

    summary = summarize_issues(issues)
    lines = [
        f"⚠️ Terdeteksi {summary['total_issues']} masalah di {summary['rows_flagged']} baris "
        f"(kemungkinan edit manual):",
        "",
    ]
    problem_label = {
        "invalid_or_missing_date": "tanggal kosong/tidak valid",
        "invalid_or_nonpositive_amount": "nominal kosong/bukan angka",
        "unknown_tipe": "tipe tidak dikenal (bukan Pemasukan/Pengeluaran)",
        "unknown_dompet_or_company": "dompet/company tidak dikenal",
        "not_a_dict": "format baris rusak",
    }
    for it in issues[:max_lines]:
        label = problem_label.get(it.problem, it.problem)
        ket = f" — {it.keterangan}" if it.keterangan else ""
        lines.append(f"• {_issue_location(it)}: {label} (nilai: {it.value!r}){ket}")

    if len(issues) > max_lines:
        lines.append(f"… dan {len(issues) - max_lines} masalah lainnya.")

    return "\n".join(lines)