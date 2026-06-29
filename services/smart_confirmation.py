"""
smart_confirmation.py - Pesan konfirmasi yang sadar konteks (Fase 3)

TUJUAN
------
Saat bot harus bertanya (dompet mana? project apa?), jangan kirim menu generik
kosong. Susun pertanyaan SPESIFIK berdasarkan apa yang SUDAH diketahui dan apa
yang KURANG, supaya terasa seperti bot yang mengerti konteks.

Sifat modul ini:
- PURE: hanya menyusun string dari input. Tidak menyentuh Sheets/jaringan/state.
- AMAN: tidak mengubah keputusan apa pun; hanya memperkaya teks prompt.
- OPSIONAL: dipakai untuk memperindah prompt yang sudah ada, dengan fallback ke
  prompt lama jika konteks tidak cukup.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _clean(value: Optional[str]) -> str:
    return str(value or "").strip()


def _format_total(transactions: List[Dict[str, Any]]) -> int:
    total = 0
    for tx in transactions or []:
        try:
            total += int(tx.get("jumlah", 0) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _first_item_label(transactions: List[Dict[str, Any]]) -> str:
    for tx in transactions or []:
        ket = _clean(tx.get("keterangan"))
        if ket:
            return ket
    return "transaksi ini"


def _rupiah(amount: int) -> str:
    return f"Rp {amount:,}".replace(",", ".")


def build_wallet_question(
    *,
    project: Optional[str] = None,
    transactions: Optional[List[Dict[str, Any]]] = None,
    debt_source: Optional[str] = None,
    base_prompt: str = "",
) -> str:
    """Susun pertanyaan dompet yang spesifik.

    Jika project diketahui, sebut nama project supaya user langsung paham
    konteksnya ("Project Ronald — dananya dari dompet mana?"). Selalu
    menyertakan base_prompt (daftar pilihan) agar user tetap bisa memilih.
    """
    project = _clean(project)
    transactions = transactions or []
    total = _format_total(transactions)
    item = _first_item_label(transactions)

    lines: List[str] = []
    if project:
        head = f"📁 Project *{project}*"
        if total > 0:
            head += f" — {item} ({_rupiah(total)})"
        lines.append(head)
        lines.append("Dananya diambil dari dompet mana?")
    else:
        if total > 0:
            lines.append(f"📝 {item} ({_rupiah(total)})")
        lines.append("Dananya dari dompet mana?")

    if debt_source:
        lines.append(f"💳 Catatan: ada konteks hutang dari *{debt_source}*.")

    if base_prompt.strip():
        lines.append("")
        lines.append(base_prompt.strip())

    return "\n".join(lines)


def build_project_question(
    *,
    suggested: Optional[str] = None,
    wallet: Optional[str] = None,
    transactions: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Susun pertanyaan nama project yang spesifik.

    Jika dompet sudah diketahui, sebutkan supaya user paham scope-nya.
    """
    wallet = _clean(wallet)
    suggested = _clean(suggested)
    transactions = transactions or []
    total = _format_total(transactions)
    item = _first_item_label(transactions)

    lines: List[str] = []
    if total > 0:
        lines.append(f"📝 {item} ({_rupiah(total)})")
    if wallet:
        lines.append(f"📌 Dompet: *{wallet}*")

    if suggested:
        lines.append(f"Maksudnya project *{suggested}*?")
        lines.append("✅ Ya — lanjutkan / ❌ ketik nama project yang benar")
    else:
        lines.append("Project ini namanya apa?")

    return "\n".join(lines)


def summarize_known_context(
    *,
    project: Optional[str] = None,
    wallet: Optional[str] = None,
    company: Optional[str] = None,
    debt_source: Optional[str] = None,
) -> str:
    """Ringkasan 1 baris konteks yang sudah diketahui (untuk transparansi).

    Mengembalikan string kosong jika tidak ada yang diketahui.
    """
    parts: List[str] = []
    if _clean(project):
        parts.append(f"project {_clean(project)}")
    if _clean(company):
        parts.append(f"company {_clean(company)}")
    if _clean(wallet):
        parts.append(f"dompet {_clean(wallet)}")
    if _clean(debt_source):
        parts.append(f"pinjam dari {_clean(debt_source)}")
    if not parts:
        return ""
    return "Terbaca: " + ", ".join(parts) + "."
