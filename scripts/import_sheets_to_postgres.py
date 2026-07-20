"""Import the existing Google Sheets ledger into configured Postgres.

Run with --dry-run first. --apply is idempotent: reruns update the same source
records and never create a duplicate financial transaction.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.ledger_store import get_status, import_projects, import_rows, normalize_row
from sheets_helper import get_raw_rows_for_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror the Google Sheets ledger to Postgres.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write to Postgres after inspecting Sheets.")
    mode.add_argument("--dry-run", action="store_true", help="Read and validate Sheets without writing to Postgres.")
    parser.add_argument("--days", type=int, default=365, help="Historical transaction window to import (default: 365).")
    parser.add_argument("--all-history", action="store_true", help="Import every historical transaction, ignoring --days.")
    args = parser.parse_args()

    rows = get_raw_rows_for_audit()
    cutoff = None if args.all_history else date.today() - timedelta(days=max(0, args.days))
    normalized_rows = [(row, normalize_row(row)) for row in rows]
    selected_rows = [
        row for row, normalized in normalized_rows
        if normalized["transaction_date"] and (cutoff is None or normalized["transaction_date"] >= cutoff)
    ]
    invalid_rows = sum(1 for _row, normalized in normalized_rows if not normalized["is_valid"])
    preview = {
        "rows_seen": len(rows),
        "selected_transactions": len(selected_rows),
        "project_index_source_rows": len(rows),
        "invalid_rows": invalid_rows,
        "window_days": "all" if args.all_history else max(0, args.days),
        "apply": bool(args.apply),
    }
    print(json.dumps(preview, ensure_ascii=False))
    if not args.apply:
        return 0

    result = import_rows(selected_rows)
    projects = import_projects(rows)
    status = get_status()
    print(json.dumps({"import": result, "projects": projects, "ledger": status}, ensure_ascii=False))
    if result["rows_upserted"] != result["rows_seen"]:
        raise RuntimeError("Import count mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
