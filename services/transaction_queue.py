"""Transaction queue normalization and merge helpers."""

import re
from typing import Dict, List, Optional, Tuple

from config.wallets import strip_company_prefix
from security import sanitize_input
from utils.amounts import parse_money_token
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
        if re.search(r"(?:rb|ribu|k|jt|juta|perak)\b", raw, re.IGNORECASE):
            parsed = parse_revision_amount(raw)
            if parsed > 0:
                return parsed
        parsed = parse_money_token(raw)
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
    - drop exact duplicates already present in the existing queue
    - preserve repeated rows inside one incoming extraction
    - prefer valid amount (>0) over zero for the same content
    """
    merged: List[dict] = []
    existing_identity_keys = set()
    existing_content_index: Dict[Tuple[str, str, str, str], int] = {}
    meta = {"added": 0, "duplicates": 0, "upgraded": 0}

    def _append_existing(raw_tx) -> None:
        tx = normalize_transaction(raw_tx)
        if not tx:
            return

        identity = tx_identity_key(tx)
        content = tx_content_key(tx)
        existing_identity_keys.add(identity)
        existing_content_index.setdefault(content, len(merged))
        merged.append(tx)

    def _upsert_incoming(raw_tx) -> None:
        tx = normalize_transaction(raw_tx)
        if not tx:
            meta["duplicates"] += 1
            return

        identity = tx_identity_key(tx)
        if identity in existing_identity_keys:
            meta["duplicates"] += 1
            return

        content = tx_content_key(tx)
        prev_idx = existing_content_index.get(content)
        if prev_idx is not None:
            prev_tx = merged[prev_idx]
            prev_amt = int(prev_tx.get("jumlah", 0) or 0)
            new_amt = int(tx.get("jumlah", 0) or 0)

            if prev_amt <= 0 < new_amt:
                prev_identity = tx_identity_key(prev_tx)
                merged[prev_idx] = tx
                existing_identity_keys.discard(prev_identity)
                existing_identity_keys.add(identity)
                meta["upgraded"] += 1
                return

            if new_amt <= 0 < prev_amt:
                meta["duplicates"] += 1
                return

        merged.append(tx)
        meta["added"] += 1

    for old_tx in existing or []:
        _append_existing(old_tx)
    for new_tx in incoming or []:
        _upsert_incoming(new_tx)

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
