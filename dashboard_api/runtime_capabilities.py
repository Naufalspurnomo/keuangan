"""Fail-closed runtime capability checks shared by API and health endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def canonical_finance_lifecycle_ready(
    config: Mapping[str, Any],
    extensions: Mapping[str, Any],
) -> bool:
    """Return true only when flags and the durable authority latch permit writes."""
    if not (
        bool(config.get("CANONICAL_FINANCE_API_ENABLED", False))
        and bool(config.get("CANONICAL_FINANCE_WRITES_ENABLED", False))
    ):
        return False
    authority = extensions.get("canonical_finance_write_authority")
    if not callable(authority):
        return False
    try:
        return authority() == "postgresql"
    except Exception:
        return False
