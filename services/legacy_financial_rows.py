"""Pure normalization for immutable legacy financial rows."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime
from typing import Any

from utils.amounts import parse_money_token


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _parse_amount(value: Any) -> int:
    raw = str(value or "").strip()
    suffix_match = re.search(
        r"\b([\d]+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta|perak)\b",
        raw,
        re.IGNORECASE,
    )
    if suffix_match:
        try:
            number = float(suffix_match.group(1).replace(",", "."))
        except ValueError:
            return 0
        suffix = suffix_match.group(2).casefold()
        multiplier = 1_000 if suffix in {"rb", "ribu", "k"} else 1_000_000
        if suffix == "perak":
            multiplier = 1
        return abs(int(round(number * multiplier)))
    return abs(parse_money_token(value))


def _source_row(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _project_id(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in row.items()
        if value is None
        or isinstance(value, (str, int, float, bool, date, datetime, list, dict))
    }


def build_source_key(row: dict[str, Any]) -> str:
    """Stable idempotency key for a Sheet row or a live bot event."""
    sheet_name = _clean(row.get("sheet_name") or row.get("dompet_sheet"), 160)
    source_block = _clean(row.get("source_block"), 40).lower() or "ledger"
    message_id = _clean(row.get("message_id"), 240)
    if message_id:
        return f"message:{sheet_name}:{source_block}:{message_id}"

    source_row = _source_row(row.get("sheet_row"))
    identity = {
        "sheet": sheet_name,
        "block": source_block,
        "row": source_row,
        "tanggal": _clean(row.get("tanggal"), 40),
        "jumlah": _clean(row.get("jumlah"), 80),
        "keterangan": _clean(row.get("keterangan"), 500),
        "project": _clean(row.get("nama_projek"), 160),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"sheet:{sheet_name}:{source_block}:{source_row}:{digest}"


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map mixed Sheet layouts into one deterministic ledger record."""
    source_sheet = _clean(row.get("sheet_name") or row.get("dompet_sheet"), 160)
    source_block = _clean(row.get("source_block"), 40).lower() or "ledger"
    amount = _parse_amount(row.get("jumlah", row.get("amount", 0)))
    transaction_type = _clean(row.get("tipe"), 24) or "Pengeluaran"
    office = source_block == "operasional"
    transaction_date = _parse_date(row.get("tanggal"))
    return {
        "source_key": build_source_key(row),
        "source_sheet": source_sheet,
        "source_row": _source_row(row.get("sheet_row")) or None,
        "source_block": source_block,
        "message_id": _clean(row.get("message_id"), 240) or None,
        "transaction_date": transaction_date,
        "amount": amount if amount > 0 else None,
        "transaction_type": transaction_type,
        "company": _clean(
            row.get("company_sheet")
            if office
            else row.get("company") or row.get("company_sheet"),
            160,
        )
        or None,
        "wallet": _clean(row.get("dompet_sheet") or source_sheet, 160) or None,
        "project": _clean(row.get("nama_projek"), 160) or None,
        "project_id": _project_id(row.get("project_id")),
        "category": _clean(row.get("kategori"), 120) or None,
        "description": _clean(row.get("keterangan"), 1000) or None,
        "recorded_by": _clean(row.get("oleh") or row.get("sender_name"), 160)
        or None,
        "input_source": _clean(row.get("source"), 80) or None,
        "source_wallet": _clean(row.get("source_wallet"), 160) or None,
        "is_valid": bool(amount > 0 and transaction_date),
        "payload": _canonical_payload(row),
    }
