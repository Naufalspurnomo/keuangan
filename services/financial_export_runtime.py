"""Production runtime loop for canonical finance -> Sheets derived export.

The worker runs in the external application runtime (for example Koyeb). It
never makes Google Sheets the financial authority: PostgreSQL remains the
source of truth and this process only drains the protected export outbox.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

from security import secure_log
from services.financial_export_worker import (
    ExportWorker,
    GoogleSheetsRemoteExport,
    PostgresExportOutbox,
)
from sheets_helper import get_spreadsheet


_DEFAULT_WORKSHEET = "_CANONICAL_FINANCE_EXPORT"
_DEFAULT_INTERVAL_SECONDS = 30
_DEFAULT_BATCH_LIMIT = 100
_DEFAULT_LEASE_SECONDS = 300
_DEFAULT_BUILD_RETRY_SECONDS = 60

_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "ready": False,
    "last_result": None,
    "last_error": None,
}


def _set_state(**changes: Any) -> None:
    with _state_lock:
        _state.update(changes)


def financial_export_health() -> dict[str, Any]:
    """Return non-secret runtime evidence for production acceptance."""
    with _state_lock:
        result = dict(_state)
    result["configured"] = bool(
        str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
        and str(os.getenv("GOOGLE_SHEETS_ID") or "").strip()
        and str(os.getenv("GOOGLE_CREDENTIALS") or "").strip()
    )
    return result


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _env_positive_int(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def build_export_worker() -> ExportWorker:
    """Build the protected PostgreSQL-to-Sheets delivery boundary."""
    dsn = str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError(
            "financial export requires the canonical external "
            "STATE_DATABASE_URL or DATABASE_URL"
        )

    workbook_id = str(os.getenv("GOOGLE_SHEETS_ID") or "").strip()
    if not workbook_id:
        raise RuntimeError("financial export requires GOOGLE_SHEETS_ID")

    if not _env_bool("FINANCIAL_EXPORT_PROTECTED_DESTINATION"):
        raise RuntimeError("financial export requires a protected destination")

    worksheet_title = str(
        os.getenv("FINANCIAL_EXPORT_WORKSHEET") or _DEFAULT_WORKSHEET
    ).strip()
    if not worksheet_title:
        raise RuntimeError("financial export requires a worksheet title")

    spreadsheet = get_spreadsheet()
    worksheet = spreadsheet.worksheet(worksheet_title)
    remote = GoogleSheetsRemoteExport(
        worksheet,
        expected_workbook_id=workbook_id,
        expected_title=worksheet_title,
        ensure_header=True,
    )
    outbox = PostgresExportOutbox(dsn)
    return ExportWorker(
        outbox=outbox,
        remote=remote,
        protected_destination=True,
        lease_seconds=_env_positive_int(
            "FINANCIAL_EXPORT_LEASE_SECONDS", default=_DEFAULT_LEASE_SECONDS
        ),
    )


def run_export_loop(
    worker: Any,
    *,
    stop_event: threading.Event,
    interval_seconds: int,
    batch_limit: int,
    on_result: Callable[[dict[str, int]], None] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """Drain the outbox until stopped; transient batch failures do not kill it."""
    while not stop_event.is_set():
        try:
            result = worker.run_once(limit=batch_limit)
            if on_result is not None:
                on_result(result)
            if result.get("claimed", 0) or result.get("failed", 0) or result.get("drifted", 0):
                secure_log("INFO", f"Financial export batch: {result}")
        except Exception as exc:
            secure_log("ERROR", f"Financial export worker failed: {type(exc).__name__}: {exc}")
        if stop_event.is_set():
            break
        if sleep is None:
            stop_event.wait(interval_seconds)
        else:
            sleep(interval_seconds)


def run_financial_export_service(
    *, stop_event: threading.Event | None = None
) -> None:
    """Run the external-runtime export service when explicitly enabled."""
    enabled = _env_bool("FINANCIAL_EXPORT_ENABLED")
    _set_state(enabled=enabled, running=False, ready=False, last_result=None, last_error=None)
    if not enabled:
        secure_log("INFO", "Financial export worker disabled")
        return

    event = stop_event or threading.Event()
    retry_seconds = _env_positive_int(
        "FINANCIAL_EXPORT_BUILD_RETRY_SECONDS", default=_DEFAULT_BUILD_RETRY_SECONDS
    )
    while not event.is_set():
        try:
            worker = build_export_worker()
            _set_state(running=True, ready=True, last_error=None)
            run_export_loop(
                worker,
                stop_event=event,
                interval_seconds=_env_positive_int(
                    "FINANCIAL_EXPORT_INTERVAL_SECONDS",
                    default=_DEFAULT_INTERVAL_SECONDS,
                ),
                batch_limit=_env_positive_int(
                    "FINANCIAL_EXPORT_BATCH_LIMIT", default=_DEFAULT_BATCH_LIMIT
                ),
                on_result=lambda result: _set_state(last_result=dict(result), last_error=None),
            )
            _set_state(running=False)
            return
        except Exception as exc:
            _set_state(running=False, ready=False, last_error=type(exc).__name__)
            secure_log(
                "ERROR",
                f"Financial export worker setup failed: {type(exc).__name__}: {exc}",
            )
            event.wait(retry_seconds)
