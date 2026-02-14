"""
allowlist.py - Allowed sender configuration

Parses ALLOWED_SENDER_IDS from environment and provides helpers to validate senders.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Set

from dotenv import load_dotenv

load_dotenv()


def _normalize_identifier(value: str) -> str:
    return value.strip().lower()


def _split_allowlist(raw_value: str) -> Set[str]:
    entries = re.split(r"[,\n]+", raw_value)
    return {_normalize_identifier(entry) for entry in entries if entry and entry.strip()}


def parse_allowed_sender_ids(env_value: str | None) -> Set[str]:
    if not env_value:
        return set()
    return _split_allowlist(env_value)


ALLOWED_SENDER_IDS = parse_allowed_sender_ids(os.getenv("ALLOWED_SENDER_IDS"))
SESSION_DELEGATE_IDS = parse_allowed_sender_ids(os.getenv("SESSION_DELEGATE_IDS"))


def _build_variants(identifier: str) -> Set[str]:
    normalized = _normalize_identifier(identifier)
    variants = {normalized}

    if normalized.startswith("@"):
        variants.add(normalized[1:])
    else:
        variants.add(f"@{normalized}")

    if normalized.startswith("+"):
        variants.add(normalized[1:])
    elif normalized.isdigit():
        variants.add(f"+{normalized}")

    return {variant for variant in variants if variant}


def is_sender_allowed(identifiers: Iterable[str | None]) -> bool:
    """Return True if allowlist is empty or any identifier is in allowlist."""
    if not ALLOWED_SENDER_IDS:
        return True

    for identifier in identifiers:
        if not identifier:
            continue
        for variant in _build_variants(str(identifier)):
            if variant in ALLOWED_SENDER_IDS:
                return True

    return False


def is_session_delegate(identifiers: Iterable[str | None]) -> bool:
    """
    Return True when any identifier is listed as a session delegate.

    Delegates are allowed to continue another user's pending session in group
    chats, but only when replying to the correct bot prompt/visual message.
    """
    if not SESSION_DELEGATE_IDS:
        return False

    for identifier in identifiers:
        if not identifier:
            continue
        for variant in _build_variants(str(identifier)):
            if variant in SESSION_DELEGATE_IDS:
                return True

    return False
