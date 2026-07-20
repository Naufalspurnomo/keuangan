"""One-time, Koyeb-safe Sheets-to-Postgres bootstrap controlled by env vars."""

from __future__ import annotations

import os
import threading
from datetime import date, timedelta

from security import secure_log
from services.ledger_store import (
    import_completed,
    import_projects,
    import_rows,
    normalize_row,
    try_import_lock,
)
from sheets_helper import get_raw_rows_for_audit


_START_LOCK = threading.Lock()
_STARTED = False


def _configured_days():
    raw = str(os.getenv("LEDGER_BOOTSTRAP_IMPORT_DAYS", "")).strip().lower()
    if not raw:
        return None
    if raw == "all":
        return None
    try:
        value = int(raw)
    except ValueError:
        secure_log("ERROR", "LEDGER_BOOTSTRAP_IMPORT_DAYS must be a positive number or 'all'")
        return False
    if value <= 0:
        secure_log("ERROR", "LEDGER_BOOTSTRAP_IMPORT_DAYS must be a positive number or 'all'")
        return False
    return value


def _select_rows(rows, days):
    cutoff = None if days is None else date.today() - timedelta(days=days)
    selected = []
    invalid = 0
    for row in rows:
        normalized = normalize_row(row)
        if not normalized["is_valid"]:
            invalid += 1
            continue
        if cutoff is None or normalized["transaction_date"] >= cutoff:
            selected.append(row)
    return selected, invalid


def _run(days) -> None:
    window = "all" if days is None else str(days)
    source = f"koyeb_bootstrap:{window}d"
    if import_completed(source):
        secure_log("INFO", "Financial ledger bootstrap already completed", source=source)
        return

    lock_connection = try_import_lock(source)
    if not lock_connection:
        secure_log("INFO", "Financial ledger bootstrap already running on another replica", source=source)
        return
    try:
        # Recheck only after obtaining the cross-replica lock.
        if import_completed(source):
            return
        rows = get_raw_rows_for_audit()
        selected, invalid = _select_rows(rows, days)
        result = import_rows(selected, source=source)
        projects = import_projects(rows)
        secure_log(
            "INFO",
            "Financial ledger bootstrap completed",
            source=source,
            rows_seen=len(rows),
            rows_imported=result["rows_upserted"],
            invalid_rows=invalid,
            projects=projects["projects_upserted"],
        )
    except Exception as exc:
        secure_log("ERROR", f"Financial ledger bootstrap failed: {type(exc).__name__}: {exc}")
    finally:
        try:
            with lock_connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (f"ledger-import:{source}",))
        finally:
            lock_connection.close()


def start_ledger_bootstrap_if_requested() -> bool:
    """Start only one non-blocking bootstrap per process; no env means no work."""
    global _STARTED
    days = _configured_days()
    if days is False:
        return False
    if str(os.getenv("LEDGER_BOOTSTRAP_IMPORT_DAYS", "")).strip() == "":
        return False
    with _START_LOCK:
        if _STARTED:
            return False
        _STARTED = True
        threading.Thread(target=_run, args=(days,), daemon=True, name="financial-ledger-bootstrap").start()
    secure_log("INFO", "Financial ledger bootstrap scheduled", window_days="all" if days is None else days)
    return True
