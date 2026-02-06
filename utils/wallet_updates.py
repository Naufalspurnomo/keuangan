"""
Helpers for wallet balance update flows.

These helpers separate two intents:
- absolute set: "set/update saldo dompet jadi X"
- delta movement: "isi/topup/tambah saldo X"
"""

from __future__ import annotations

import re
from typing import Dict, Iterable


ABSOLUTE_SET_PATTERNS = (
    re.compile(r"\bset\s+saldo\b", re.IGNORECASE),
    re.compile(r"\bupdate\s+saldo\b", re.IGNORECASE),
    re.compile(r"\bsaldo\s+awal\b", re.IGNORECASE),
    re.compile(r"\bsaldo\s+sekarang\b", re.IGNORECASE),
    re.compile(r"\binisialisasi\s+saldo\b", re.IGNORECASE),
    re.compile(r"\bsamakan\s+saldo\b", re.IGNORECASE),
)


def is_absolute_balance_update(text: str) -> bool:
    """Return True when text indicates target saldo should be set absolutely."""
    if not text:
        return False
    clean = text.lower().strip()
    return any(p.search(clean) for p in ABSOLUTE_SET_PATTERNS)


def pick_wallet_target_amount(transactions: Iterable[Dict]) -> int:
    """
    Pick target amount for wallet update from extracted transactions.
    Uses the largest positive amount to avoid small numeric noise.
    """
    best = 0
    for tx in transactions or []:
        try:
            amt = int(tx.get("jumlah", 0) or 0)
        except Exception:
            amt = 0
        if amt > best:
            best = amt
    return int(best)


def compute_balance_adjustment(current_balance: int, target_balance: int) -> Dict[str, int | str]:
    """
    Compute adjustment transaction needed to set current balance to target.

    Returns:
    - delta: signed adjustment (target - current)
    - amount: absolute amount for transaction row
    - tipe: "Pemasukan" when increase, "Pengeluaran" when decrease, "" when no change
    """
    current = int(current_balance or 0)
    target = int(target_balance or 0)
    delta = target - current
    if delta > 0:
        return {"delta": delta, "amount": delta, "tipe": "Pemasukan"}
    if delta < 0:
        return {"delta": delta, "amount": abs(delta), "tipe": "Pengeluaran"}
    return {"delta": 0, "amount": 0, "tipe": ""}
