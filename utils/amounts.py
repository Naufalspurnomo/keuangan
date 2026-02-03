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
