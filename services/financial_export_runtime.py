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
    "drift_latched": False,
    "last_drift": None,
}


def _set_state(**changes: Any) -> None:
    with _state_lock:
        _state.update(changes)


def _record_export_result(result: dict[str, Any]) -> None:
    """Record a batch without treating an empty batch as drift recovery."""

    observed = dict(result)
    with _state_lock:
        _state["last_result"] = observed
        _state["last_error"] = None
        if int(observed.get("drifted", 0) or 0) > 0:
            _state["drift_latched"] = True
            _state["last_drift"] = observed
            _state["ready"] = False
        elif observed.get("recovery_verified") is True:
            _state["drift_latched"] = False
            _state["last_drift"] = None
            _state["ready"] = True


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


def _export_enabled() -> bool:
    """Default on only inside a fully configured Koyeb production runtime."""
    external_ready = bool(
        str(os.getenv("KOYEB_SERVICE_ID") or "").strip()
        and str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
        and str(os.getenv("GOOGLE_SHEETS_ID") or "").strip()
        and str(os.getenv("GOOGLE_CREDENTIALS") or "").strip()
    )
    return _env_bool("FINANCIAL_EXPORT_ENABLED", default=external_ready)


def _worksheet_is_protected(spreadsheet: Any, worksheet: Any) -> bool:
    metadata = spreadsheet.fetch_sheet_metadata(
        params={
            "fields": (
                "sheets(properties(sheetId),"
                "protectedRanges(range,warningOnly))"
            )
        }
    )
    worksheet_id = int(getattr(worksheet, "id"))
    for sheet in metadata.get("sheets", []):
        if int(sheet.get("properties", {}).get("sheetId", -1)) != worksheet_id:
            continue
        for protected in sheet.get("protectedRanges", []):
            if protected.get("warningOnly"):
                continue
            cell_range = protected.get("range", {})
            if int(cell_range.get("sheetId", -1)) != worksheet_id:
                continue
            start_column = int(cell_range.get("startColumnIndex", 0))
            end_column = cell_range.get("endColumnIndex")
            if start_column == 0 and (end_column is None or int(end_column) >= 10):
                return True
    return False


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

    protected_setting = os.getenv("FINANCIAL_EXPORT_PROTECTED_DESTINATION")
    if protected_setting is not None and not _env_bool(
        "FINANCIAL_EXPORT_PROTECTED_DESTINATION"
    ):
        raise RuntimeError("financial export requires a protected destination")

    worksheet_title = str(
        os.getenv("FINANCIAL_EXPORT_WORKSHEET") or _DEFAULT_WORKSHEET
    ).strip()
    if not worksheet_title:
        raise RuntimeError("financial export requires a worksheet title")

    spreadsheet = get_spreadsheet()
    worksheet = spreadsheet.worksheet(worksheet_title)
    if not _worksheet_is_protected(spreadsheet, worksheet):
        raise RuntimeError("financial export destination is not protected")
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
    on_result: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """Drain the outbox until stopped; transient batch failures do not kill it."""
    while not stop_event.is_set():
        try:
            if worker.has_unresolved_drift():
                result = worker.recover_verified_drift()
                if on_result is not None:
                    on_result(result)
                if not result.get("recovery_verified"):
                    if result.get("examined", 0):
                        secure_log("INFO", f"Financial export recovery: {result}")
                    if stop_event.is_set():
                        break
                    if sleep is None:
                        stop_event.wait(interval_seconds)
                    else:
                        sleep(interval_seconds)
                    continue
            result = worker.run_once(limit=batch_limit)
            if (
                worker.has_unresolved_drift() is False
                and int(result.get("drifted", 0) or 0) == 0
            ):
                result = {**result, "recovery_verified": True}
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
    enabled = _export_enabled()
    _set_state(
        enabled=enabled,
        running=False,
        ready=False,
        last_result=None,
        last_error=None,
        drift_latched=False,
        last_drift=None,
    )
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
            drift_probe = getattr(worker, "has_unresolved_drift", None)
            unresolved_drift = bool(drift_probe()) if callable(drift_probe) else False
            _set_state(
                running=True,
                ready=not unresolved_drift,
                last_error=None,
                drift_latched=unresolved_drift,
                last_drift={"source": "postgresql", "unresolved": True} if unresolved_drift else None,
            )
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
                on_result=_record_export_result,
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
