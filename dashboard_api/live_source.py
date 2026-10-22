"""Read-only live dashboard source using the bot's canonical Sheets helpers."""

from __future__ import annotations

import copy
import logging
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
_cold_start_lock = threading.Lock()
_source_lock = threading.Lock()
_cached_at = 0.0
_cached_snapshot: dict[str, Any] | None = None
_refreshing = False
_last_refresh_failed_at = 0.0
_DEFAULT_CACHE_SECONDS = 5
_MAX_CACHE_SECONDS = 5
_REFRESH_RETRY_SECONDS = 30
logger = logging.getLogger(__name__)


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


def _read_fresh_snapshot(*, force_refresh: bool) -> dict[str, Any]:
    with _source_lock:
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
        return build_live_snapshot(
            raw_rows,
            balances,
            _read_debts(spreadsheet),
            now=datetime.now(timezone.utc),
        )


def _annotate_cached(snapshot: dict[str, Any], source_status: str) -> dict[str, Any]:
    result = copy.deepcopy(snapshot)
    result.setdefault("meta", {})["source_status"] = source_status
    return result


def _refresh_cache_in_background() -> None:
    global _cached_at, _cached_snapshot, _refreshing, _last_refresh_failed_at
    try:
        snapshot = _read_fresh_snapshot(force_refresh=True)
        snapshot.setdefault("meta", {})["source_status"] = "live"
        with _cache_lock:
            _cached_snapshot = snapshot
            _cached_at = time.monotonic()
            _last_refresh_failed_at = 0.0
    except Exception as exc:
        logger.warning("Live dashboard background refresh failed: %s", type(exc).__name__)
        with _cache_lock:
            _last_refresh_failed_at = time.monotonic()
    finally:
        with _cache_lock:
            _refreshing = False


def load_live_snapshot(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return immediately from cache after cold start; refresh stale data asynchronously."""
    global _cached_at, _cached_snapshot, _refreshing, _last_refresh_failed_at

    if force_refresh:
        snapshot = _read_fresh_snapshot(force_refresh=True)
        snapshot.setdefault("meta", {})["source_status"] = "live"
        with _cache_lock:
            _cached_snapshot = snapshot
            _cached_at = time.monotonic()
            _last_refresh_failed_at = 0.0
        return copy.deepcopy(snapshot)

    now_monotonic = time.monotonic()
    with _cache_lock:
        if _cached_snapshot is not None:
            age = now_monotonic - _cached_at
            if age < _cache_seconds():
                return _annotate_cached(_cached_snapshot, "live")
            retry_ready = _last_refresh_failed_at == 0.0 or now_monotonic - _last_refresh_failed_at >= _REFRESH_RETRY_SECONDS
            if not _refreshing and retry_ready:
                _refreshing = True
                threading.Thread(target=_refresh_cache_in_background, daemon=True).start()
                status = "refreshing"
            else:
                status = "degraded" if _last_refresh_failed_at else "refreshing"
            return _annotate_cached(_cached_snapshot, status)

    with _cold_start_lock:
        with _cache_lock:
            if _cached_snapshot is not None:
                return _annotate_cached(_cached_snapshot, "live")
        snapshot = _read_fresh_snapshot(force_refresh=False)
        snapshot.setdefault("meta", {})["source_status"] = "live"
        with _cache_lock:
            _cached_snapshot = snapshot
            _cached_at = time.monotonic()
            _last_refresh_failed_at = 0.0
        return copy.deepcopy(snapshot)


def reset_live_snapshot_cache_for_tests() -> None:
    global _cached_at, _cached_snapshot, _refreshing, _last_refresh_failed_at
    with _cache_lock:
        _cached_at = 0.0
        _cached_snapshot = None
        _refreshing = False
        _last_refresh_failed_at = 0.0
