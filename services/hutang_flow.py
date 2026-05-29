"""Helpers for wallet debt-payment and balance replies."""

import re
from typing import Dict, List, Optional

from config.wallets import DOMPET_ALIASES
from services.state_manager import set_pending_confirmation
from sheets_helper import find_open_hutang, invalidate_dashboard_cache, settle_hutang
from utils.parsers import parse_revision_amount


DEBT_PAYMENT_KEYWORDS = [
    "bayar", "lunas", "lunasi", "pelunasan", "cicil", "cicilan", "angsuran"
]


def is_debt_payment_text(text: str) -> bool:
    lower = (text or "").lower()
    if not re.search(r"\b(utang|hutang)\b", lower):
        return False
    return any(re.search(rf"\b{re.escape(k)}\b", lower) for k in DEBT_PAYMENT_KEYWORDS)


def extract_dompet_mentions(text: str) -> List[str]:
    lower = (text or "").lower()
    aliases = sorted(DOMPET_ALIASES.items(), key=lambda x: -len(x[0]))
    seen = set()
    dompets: List[str] = []
    for alias, dompet in aliases:
        if alias and alias in lower:
            if dompet not in seen:
                seen.add(dompet)
                dompets.append(dompet)
    return dompets


def pick_dompet_by_prep(text: str, preps: List[str]) -> Optional[str]:
    lower = (text or "").lower()
    aliases = sorted(DOMPET_ALIASES.items(), key=lambda x: -len(x[0]))
    for prep in preps:
        for alias, dompet in aliases:
            pattern = rf"\b{re.escape(prep)}\b[^a-z0-9]{{0,10}}(?:dompet|rekening|rek|wallet)?\s*{re.escape(alias)}\b"
            if re.search(pattern, lower):
                return dompet
    return None


def format_hutang_paid_response(info: Dict) -> str:
    """Format response for a settled hutang with balance details."""
    amount = int(info.get('amount', 0) or 0)
    borrower = info.get('yang_hutang', '-')
    lender = info.get('yang_dihutangi', '-')
    ket = info.get('keterangan', '-')

    lines = [
        f"âœ… Hutang #{info['no']} ditandai PAID.",
        f"ðŸ“ {ket}",
        f"ðŸ’° {borrower} â†’ {lender}",
        f"ðŸ’µ Rp {amount:,}",
    ]
    if info.get('settled'):
        lines.append("")
        lines.append(f"ðŸ“Š Saldo diperbarui:")
        lines.append(f"   ðŸ’¸ {borrower}: Pengeluaran Rp {amount:,}")
        lines.append(f"   ðŸ’° {lender}: Pemasukan Rp {amount:,}")

    return "\n".join(lines).replace(',', '.')


def build_saldo_message(balances: Dict[str, Dict]) -> str:
    """Build wallet-balance message using real-balance components."""
    msg = "ðŸ’° SALDO DOMPET REAL\n\n"
    for dompet, info in balances.items():
        masuk = int(info.get('pemasukan', 0) or 0)
        keluar = int(info.get('pengeluaran', 0) or 0)
        op = int(info.get('operational_debit', 0) or 0)
        hutang_open = int(info.get('utang_open_in', 0) or 0)
        hutang_paid = int(info.get('utang_paid_in', 0) or 0)
        saldo = int(info.get('saldo', 0) or 0)

        msg += f"ðŸ“Š {dompet}\n"
        msg += f"   Masuk: Rp {masuk:,}\n".replace(',', '.')
        msg += f"   Keluar Internal: Rp {keluar:,}\n".replace(',', '.')
        msg += f"   Potongan Operasional: Rp {op:,}\n".replace(',', '.')
        msg += f"   Penyesuaian Hutang OPEN: Rp {hutang_open:,}\n".replace(',', '.')
        if hutang_paid:
            msg += f"   Hutang PAID (audit): Rp {hutang_paid:,}\n".replace(',', '.')
        msg += f"   Saldo Real: Rp {saldo:,}\n\n".replace(',', '.')

    return msg


def extract_repayment_amount_from_transactions(transactions: list) -> int:
    """
    Pick the most likely repayment amount from extracted transactions.
    Ignores transfer/admin fee lines and prefers the largest positive amount.
    """
    if not transactions:
        return 0

    positive_amounts = []
    main_amounts = []
    for tx in transactions:
        try:
            amount = int(tx.get('jumlah', 0) or 0)
        except Exception:
            amount = 0
        if amount <= 0:
            continue

        positive_amounts.append(amount)
        desc = str(tx.get('keterangan', '') or '').lower()
        if re.search(r"\b(biaya transfer|fee transfer|fee admin|admin bank)\b", desc):
            continue
        main_amounts.append(amount)

    if main_amounts:
        return max(main_amounts)
    if positive_amounts:
        return max(positive_amounts)
    return 0


def handle_auto_hutang_payment(
    text: str,
    user_id: str = "",
    chat_id: str = "",
    amount_hint: int = 0,
) -> Optional[str]:
    """
    Match debt-payment intent from natural language and ask explicit confirmation
    before settling (except explicit "no X" command).
    """
    if not is_debt_payment_text(text):
        return None

    lower = (text or "").lower()
    if re.search(r"\b(projek|project|proyek|prj)\b", lower):
        return None
    # Allow direct "no 3" or "nomor 3"
    m_no = re.search(r"\b(?:no|nomor)\.?\s*(\d+)\b", lower)
    if m_no:
        info = settle_hutang(int(m_no.group(1)), sender_name="System", source="WhatsApp")
        if not info:
            return "âŒ No hutang tidak ditemukan."
        if info.get('error'):
            return f"âŒ Pelunasan hutang #{info.get('no', '?')} gagal.\nâš ï¸ {info['error']}"
        invalidate_dashboard_cache()
        return format_hutang_paid_response(info)

    amount = parse_revision_amount(text) or int(amount_hint or 0)
    lender = pick_dompet_by_prep(text, ["ke", "kepada", "kpd", "untuk"])
    borrower = pick_dompet_by_prep(text, ["dari", "dr"])

    if not lender and not borrower:
        return (
            "ðŸ¤” Ini pelunasan hutang dompet atau transaksi project?\n"
            "Jika hutang dompet, tulis: bayar hutang ke TX SBY 2jt / bayar hutang no 3.\n"
            "Jika transaksi project, tulis kata 'projek'."
        )

    def _compact_candidates(items: list) -> list:
        compact = []
        for item in items:
            compact.append({
                'no': str(item.get('no', '') or '').strip(),
                'yang_hutang': str(item.get('yang_hutang', '-') or '-'),
                'yang_dihutangi': str(item.get('yang_dihutangi', '-') or '-'),
                'amount': int(item.get('amount', 0) or 0),
                'keterangan': str(item.get('keterangan', '-') or '-'),
            })
        return compact

    # Try strict match first (by pair + amount)
    candidates = []
    if amount > 0:
        candidates = find_open_hutang(
            yang_hutang=borrower,
            yang_dihutangi=lender,
            amount=amount
        )
        if not candidates:
            candidates = find_open_hutang(
                yang_hutang=borrower or None,
                yang_dihutangi=lender or None,
                amount=amount
            )
        # Amount is known but no exact match for same pair.
        if not candidates and (borrower or lender):
            pair_candidates = find_open_hutang(
                yang_hutang=borrower or None,
                yang_dihutangi=lender or None,
                amount=None
            )
            if pair_candidates:
                lines = [
                    "âš ï¸ Nominal pelunasan tidak cocok dengan hutang OPEN untuk pasangan dompet ini.",
                    f"Nominal terdeteksi: Rp {amount:,}".replace(',', '.'),
                    "",
                    "Hutang OPEN yang tersedia:",
                ]
                for item in pair_candidates[:5]:
                    lines.append(
                        f"#{item['no']} {item.get('yang_hutang','-')} â†’ {item.get('yang_dihutangi','-')} "
                        f"Rp {item.get('amount',0):,} ({item.get('keterangan','-')})"
                    )
                lines.append("")
                lines.append("Ketik: bayar hutang no <nomor> untuk memilih yang benar.")
                return "\n".join(lines).replace(',', '.')

    # Fallback: match by pair only (only when amount is unknown)
    if not candidates and amount <= 0:
        candidates = find_open_hutang(
            yang_hutang=borrower or None,
            yang_dihutangi=lender or None,
            amount=None
        )

    if not candidates and amount > 0:
        candidates = find_open_hutang(amount=amount)

    if not candidates:
        return "âŒ Tidak ada hutang OPEN yang cocok. Tulis contoh: bayar hutang ke TX SBY 2jt."

    if len(candidates) > 1:
        if user_id and chat_id:
            compact_candidates = _compact_candidates(candidates[:8])
            lines = ["ðŸ¤” Ketemu beberapa hutang OPEN. Pilih yang mau dilunasi:"]
            for idx, item in enumerate(compact_candidates, start=1):
                lines.append(
                    f"{idx}. #{item['no']} {item['yang_hutang']} â†’ {item['yang_dihutangi']} Rp {item['amount']:,} ({item['keterangan']})"
                )
            lines.append("")
            lines.append(f"Balas angka 1-{len(compact_candidates)} untuk konfirmasi pelunasan.")
            lines.append("Ketik /cancel untuk batal.")
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'hutang_payment_selection',
                    'candidates': compact_candidates,
                    'raw_text': text,
                }
            )
            return "\n".join(lines).replace(',', '.')

        lines = ["ðŸ¤” Ada beberapa hutang OPEN. Balas dengan format: `bayar hutang no 3`."]
        for item in candidates[:5]:
            lines.append(
                f"#{item['no']} {item.get('yang_hutang','-')} â†’ {item.get('yang_dihutangi','-')} "
                f"Rp {item.get('amount',0):,} ({item.get('keterangan','-')})"
            )
        return "\n".join(lines).replace(',', '.')

    # Single candidate: require explicit confirmation.
    chosen = _compact_candidates([candidates[0]])[0]
    if user_id and chat_id:
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'hutang_payment_selection',
                'candidates': [chosen],
                'raw_text': text,
            }
        )
        lines = [
            "ðŸ¤” Konfirmasi pelunasan hutang ini?",
            f"#{chosen['no']} {chosen['yang_hutang']} â†’ {chosen['yang_dihutangi']}",
            f"Rp {chosen['amount']:,} ({chosen['keterangan']})",
            "",
            "Balas Ya untuk lunasi. Batal untuk cancel.",
            "Bisa juga balas angka 1.",
        ]
        if amount > 0 and amount != int(chosen['amount'] or 0):
            lines.insert(3, f"Nominal terdeteksi: Rp {amount:,} (berbeda dari hutang).".replace(',', '.'))
        return "\n".join(lines).replace(',', '.')

    return (
        "ðŸ¤” Ketemu 1 hutang OPEN. "
        f"Lunasi dengan perintah: bayar hutang no {chosen['no']}"
    )
