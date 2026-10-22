"""Read-only live dashboard source using the bot's canonical Sheets helpers."""

from __future__ import annotations

import copy
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from config.constants import (
    HUTANG_COLS,
    HUTANG_DATA_START,
    HUTANG_SHEET_NAME,
    OPERASIONAL_SHEET_NAME,
)
from config.wallets import DOMPET_SHEETS
from dashboard_api.live_snapshot import build_live_snapshot
from sheets_helper import (
    get_raw_rows_for_audit,
    get_spreadsheet,
    get_wallet_balances,
    is_internal_transfer_transaction,
)
from utils.amounts import parse_money_token


_cache_lock = threading.Lock()
_cached_at = 0.0
_cached_snapshot: dict[str, Any] | None = None
_DEFAULT_CACHE_SECONDS = 5
_MAX_CACHE_SECONDS = 5


def _cache_seconds() -> int:
    try:
        configured = int(os.getenv("DASHBOARD_LIVE_CACHE_SECONDS", str(_DEFAULT_CACHE_SECONDS)))
    except ValueError:
        configured = _DEFAULT_CACHE_SECONDS
    return max(1, min(configured, _MAX_CACHE_SECONDS))


def _required_worksheets() -> list[str]:
    return [*DOMPET_SHEETS, OPERASIONAL_SHEET_NAME, HUTANG_SHEET_NAME]


def _verify_required_worksheets(spreadsheet: Any) -> None:
    """Resolve every required sheet before helpers that have create-on-missing behavior."""
    missing = []
    for name in _required_worksheets():
        try:
            spreadsheet.worksheet(name)
        except Exception:
            missing.append(name)
    if missing:
        raise RuntimeError(f"required dashboard worksheets unavailable: {', '.join(missing)}")


def _cell(row: list[str], column: str) -> str:
    index = HUTANG_COLS[column] - 1
    return row[index] if len(row) > index else ""


def _read_debts(spreadsheet: Any) -> list[dict[str, Any]]:
    rows = spreadsheet.worksheet(HUTANG_SHEET_NAME).get_all_values()[HUTANG_DATA_START - 1 :]
    debts = []
    for sheet_row, row in enumerate(rows, start=HUTANG_DATA_START):
        status = _cell(row, "STATUS").strip().upper()
        amount = parse_money_token(_cell(row, "NOMINAL"))
        if not status or amount <= 0:
            continue
        debts.append(
            {
                "source_key": f"{HUTANG_SHEET_NAME}:{sheet_row}",
                "date": _cell(row, "TANGGAL"),
                "amount": amount,
                "notes": _cell(row, "KETERANGAN"),
                "borrower": _cell(row, "YANG_HUTANG"),
                "lender": _cell(row, "YANG_DIHUTANGI"),
                "status": status,
            }
        )
    return debts


def load_live_snapshot(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return one cached immutable projection; never writes to Sheets."""
    global _cached_at, _cached_snapshot

    ttl = _cache_seconds()
    with _cache_lock:
        now_monotonic = time.monotonic()
        if not force_refresh and _cached_snapshot is not None and now_monotonic - _cached_at < ttl:
            return copy.deepcopy(_cached_snapshot)

        spreadsheet = get_spreadsheet()
        _verify_required_worksheets(spreadsheet)
        raw_rows = get_raw_rows_for_audit()
        for row in raw_rows:
            row["internal_movement"] = is_internal_transfer_transaction(row)
        balances = get_wallet_balances(
            force_refresh=force_refresh,
            strict=True,
            spreadsheet=spreadsheet,
        )
        snapshot = build_live_snapshot(
            raw_rows,
            balances,
            _read_debts(spreadsheet),
            now=datetime.now(timezone.utc),
        )
        _cached_snapshot = snapshot
        _cached_at = now_monotonic
        return copy.deepcopy(snapshot)


def reset_live_snapshot_cache_for_tests() -> None:
    global _cached_at, _cached_snapshot
    with _cache_lock:
        _cached_at = 0.0
        _cached_snapshot = None
