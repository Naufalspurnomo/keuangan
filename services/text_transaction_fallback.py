"""Small grounded fallback for obvious one-line finance messages."""

from __future__ import annotations

import re
from datetime import datetime

from config.constants import OPERATIONAL_KEYWORDS
from security import validate_transaction_data
from utils.amounts import has_amount_pattern, parse_money_token
from utils.parsers import parse_revision_amount


_MONEY_TOKEN_RE = re.compile(
    r"\b[0-9OoIl]{1,3}(?:[.,\s][0-9OoIl]{3})+(?:[.,][0-9OoIl]{2})?\b|"
    r"\b[0-9OoIl]+[.,][0-9OoIl]{2}\b|"
    r"\b[0-9OoIl]{4,}\b"
)
_SHORTHAND_AMOUNT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:rb|ribu|k|jt|juta|perak)\b",
    re.IGNORECASE,
)
_PROJECT_RE = re.compile(
    r"\b(?:projek|project|proyek|prj)\b\s+(.+)",
    re.IGNORECASE,
)


def extract_single_text_amount(text: str) -> int:
    """Return one grounded amount, or zero when the message has many/none."""
    if not text or "Receipt/Struk content:" in text:
        return 0

    values = []
    for token in _MONEY_TOKEN_RE.findall(text):
        value = parse_money_token(token)
        if value >= 100 and value not in values:
            values.append(value)
    for token in _SHORTHAND_AMOUNT_RE.findall(text):
        value = parse_revision_amount(token)
        if value >= 100 and value not in values:
            values.append(value)
    return values[0] if len(values) == 1 else 0


def _explicit_project(text: str) -> str:
    match = _PROJECT_RE.search(text or "")
    if not match:
        return ""
    value = re.split(
        r"\b(?:dompet|wallet|rekening|rek|utang|hutang|minjam|minjem|pinjam|dari|dr|via|operasional|kantor)\b",
        match.group(1),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.sub(r"\s+", " ", value).strip(" ,.;:-")
    return value[:100]


def build_text_transaction_fallback(text: str, amount: int) -> dict:
    """Build one transaction only when action, amount, and description are grounded."""
    lower = (text or "").lower()
    if amount < 100 or not has_amount_pattern(text):
        return {}
    if not re.search(
        r"\b(?:bayar|biaya|beli|fee|gaji|upah|honor|reimburse(?:ment)?|transfer|terima|dp|masuk|keluar|catat|admin)\b",
        lower,
    ):
        return {}

    description = _MONEY_TOKEN_RE.sub(" ", text, count=1)
    description = _SHORTHAND_AMOUNT_RE.sub(" ", description, count=1)
    description = re.sub(r"^\s*(?:/|\+)?catat\b", "", description, flags=re.IGNORECASE)
    description = re.split(
        r"\b(?:projek|project|proyek|prj|operasional|operational|kantor|office)\b",
        description,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    description = re.sub(r"\s+", " ", description).strip(" ,.;:-")
    if len(description) < 3:
        return {}

    operational = bool(
        re.search(r"\b(?:operasional|operational|kantor|office)\b", lower)
        or any(re.search(r"\b" + re.escape(keyword) + r"\b", lower) for keyword in OPERATIONAL_KEYWORDS)
    )
    income = bool(
        re.search(r"\b(?:terima|diterima|pemasukan|transfer masuk|dp masuk|termin masuk|refund|cashback)\b", lower)
    )
    project = "" if operational else _explicit_project(text)
    transaction = {
        "tanggal": datetime.now().strftime("%Y-%m-%d"),
        "kategori": "Lain-lain",
        "keterangan": description[:200],
        "jumlah": amount,
        "tipe": "Pemasukan" if income else "Pengeluaran",
        "nama_projek": project,
        "company": None,
    }
    if not operational and not project:
        transaction["needs_project"] = True

    valid, _error, sanitized = validate_transaction_data(transaction)
    return sanitized if valid else {}
