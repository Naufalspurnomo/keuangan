"""
amounts.py - Shared helpers for amount detection and normalization.

Centralizes amount pattern detection to avoid drift across modules.
"""
from __future__ import annotations

import re
from typing import Iterable, Pattern


AMOUNT_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"rp[\s.]*\d{1,3}(?:[.,]\d{3})+", re.IGNORECASE),  # Rp 10.000.000
    re.compile(r"rp[\s.]*\d+", re.IGNORECASE),                    # Rp 50000, rp50000
    re.compile(r"\d+[\s]*(rb|ribu|k)", re.IGNORECASE),   # 50rb, 50 ribu, 50k
    re.compile(r"\d+[\s]*(jt|juta)", re.IGNORECASE),     # 1jt, 1 juta
    re.compile(r"\d{1,3}(?:[.,]\d{3})+"),                # 10.984.668 or 10,984,668
    re.compile(r"\d{4,}"),                               # 50000 (4+ digits)
)


def parse_money_token(token: str) -> int:
    """
    Parse a money token with Indonesian or international separators.

    Examples:
    - 480,000.00 -> 480000
    - 480.000,00 -> 480000
    - 10.984.668 -> 10984668
    """
    if token is None:
        return 0

    if isinstance(token, (int, float)):
        try:
            return int(abs(token))
        except (TypeError, ValueError, OverflowError):
            return 0

    text = str(token).strip()
    if not text:
        return 0

    text = (
        text.replace("O", "0")
        .replace("o", "0")
        .replace("I", "1")
        .replace("l", "1")
        .replace("|", "1")
    )
    text = re.sub(r"[^\d.,\s]", "", text)
    text = re.sub(r"\s+", ".", text.strip())
    if not text or not re.search(r"\d", text):
        return 0

    has_dot = "." in text
    has_comma = "," in text

    def strip_separators(value: str) -> str:
        return value.replace(".", "").replace(",", "")

    if has_dot and has_comma:
        last_sep = re.search(r"([.,])(\d+)$", text)
        if last_sep:
            digits_after = len(last_sep.group(2))
            head = text[:last_sep.start(1)]
            if digits_after <= 2 and re.match(r"^\d{1,3}([.,]\d{3})+$", head):
                try:
                    return int(strip_separators(head))
                except ValueError:
                    return 0
        try:
            return int(strip_separators(text))
        except ValueError:
            return 0

    if has_dot or has_comma:
        sep = "." if has_dot else ","
        sep_re = re.escape(sep)
        if re.match(rf"^\d{{1,3}}(?:{sep_re}\d{{3}})+$", text):
            try:
                return int(text.replace(sep, ""))
            except ValueError:
                return 0
        decimal_match = re.match(rf"^(\d+){sep_re}(\d{{1,2}})$", text)
        if decimal_match:
            try:
                return int(decimal_match.group(1))
            except ValueError:
                return 0
        try:
            return int(text.replace(sep, ""))
        except ValueError:
            return 0

    try:
        return int(text)
    except ValueError:
        return 0


def has_amount_pattern(text: str, patterns: Iterable[Pattern[str]] = AMOUNT_PATTERNS) -> bool:
    """Check if text contains recognizable amount pattern."""
    if not text:
        return False
    for pattern in patterns:
        if pattern.search(text):
            return True
    # Fallback: detect separators + long digits (e.g., "10.984.668 rupiah")
    if re.search(r"[.,]", text):
        compact = re.sub(r"[.,\s]", "", text)
        if re.search(r"\d{4,}", compact):
            return True
    return False
