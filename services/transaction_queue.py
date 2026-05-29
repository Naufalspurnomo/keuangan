"""Transaction queue normalization and merge helpers."""

import re
from typing import Dict, List, Optional, Tuple

from config.wallets import strip_company_prefix
from security import sanitize_input
from utils.parsers import parse_revision_amount


def normalize_amount(value) -> int:
    """Best-effort parse amount to non-negative integer."""
    try:
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return abs(value)
        if isinstance(value, float):
            return abs(int(value))
        raw = str(value).strip()
        if not raw:
            return 0
        parsed = parse_revision_amount(raw)
        if parsed > 0:
            return parsed
        raw = raw.replace("rp", "").replace("Rp", "").replace("RP", "")
        digits = re.sub(r"[^0-9]", "", raw)
        return int(digits) if digits else 0
    except Exception:
        return 0


def normalize_key_text(value) -> str:
    text_value = sanitize_input(str(value or "")).lower().strip()
    return re.sub(r"\s+", " ", text_value)


def normalize_transaction(tx: dict) -> Optional[dict]:
    if not isinstance(tx, dict):
        return None

    normalized = dict(tx)
    normalized["jumlah"] = normalize_amount(normalized.get("jumlah", 0))

    ket = sanitize_input(str(normalized.get("keterangan", "") or "")).strip()
    normalized["keterangan"] = ket[:200] if ket else "Transaksi"

    tipe = normalized.get("tipe", "Pengeluaran")
    if tipe not in ("Pemasukan", "Pengeluaran"):
        tipe = "Pengeluaran"
    normalized["tipe"] = tipe

    if normalized["jumlah"] <= 0:
        normalized["needs_amount"] = True
    else:
        normalized.pop("needs_amount", None)
    return normalized


def tx_content_key(tx: dict) -> Tuple[str, str, str, str]:
    project = strip_company_prefix(str(tx.get("nama_projek", "") or ""))
    return (
        normalize_key_text(tx.get("tipe", "Pengeluaran")),
        normalize_key_text(tx.get("keterangan", "")),
        normalize_key_text(project),
        normalize_key_text(tx.get("kategori", "")),
    )


def tx_identity_key(tx: dict) -> Tuple[str, str, str, str, int]:
    content = tx_content_key(tx)
    amount = int(tx.get("jumlah", 0) or 0)
    return (content[0], content[1], content[2], content[3], amount)


def merge_transaction_queue(existing: list, incoming: list) -> Tuple[list, dict]:
    """
    Merge queue safely:
    - normalize every tx
    - drop exact duplicates
    - prefer valid amount (>0) over zero for the same content
    """
    merged: List[dict] = []
    identity_index: Dict[Tuple[str, str, str, str, int], int] = {}
    content_index: Dict[Tuple[str, str, str, str], int] = {}
    meta = {"added": 0, "duplicates": 0, "upgraded": 0}

    def _upsert(raw_tx, is_incoming: bool) -> None:
        tx = normalize_transaction(raw_tx)
        if not tx:
            if is_incoming:
                meta["duplicates"] += 1
            return

        identity = tx_identity_key(tx)
        if identity in identity_index:
            if is_incoming:
                meta["duplicates"] += 1
            return

        content = tx_content_key(tx)
        prev_idx = content_index.get(content)
        if prev_idx is not None:
            prev_tx = merged[prev_idx]
            prev_amt = int(prev_tx.get("jumlah", 0) or 0)
            new_amt = int(tx.get("jumlah", 0) or 0)

            if prev_amt <= 0 < new_amt:
                prev_identity = tx_identity_key(prev_tx)
                merged[prev_idx] = tx
                identity_index.pop(prev_identity, None)
                identity_index[identity] = prev_idx
                if is_incoming:
                    meta["upgraded"] += 1
                return

            if new_amt <= 0 < prev_amt:
                if is_incoming:
                    meta["duplicates"] += 1
                return

        insert_idx = len(merged)
        merged.append(tx)
        identity_index[identity] = insert_idx
        content_index.setdefault(content, insert_idx)
        if is_incoming:
            meta["added"] += 1

    for old_tx in existing or []:
        _upsert(old_tx, is_incoming=False)
    for new_tx in incoming or []:
        _upsert(new_tx, is_incoming=True)

    return merged, meta


def first_missing_amount_tx(transactions: list) -> Optional[dict]:
    for tx in transactions or []:
        try:
            amount = int(tx.get("jumlah", 0) or 0)
        except Exception:
            amount = 0
        if tx.get("needs_amount") or amount <= 0:
            return tx
    return None
