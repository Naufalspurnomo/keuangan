#!/usr/bin/env python3
"""Check or explicitly apply the additive durable-inbox review schema."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "dashboard_api" / "migrations" / "004_inbox_review.sql"
_CONFIRMATION = "APPLY_INBOX_REVIEW_SCHEMA"


def _dsn() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def apply_migration(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(MIGRATION.read_text(encoding="utf-8"))


def schema_health(dsn: str) -> dict[str, Any]:
    previous = os.environ.get("STATE_DATABASE_URL")
    os.environ["STATE_DATABASE_URL"] = dsn
    try:
        from services.durable_inbox import inbox_review_schema_health

        return inbox_review_schema_health()
    finally:
        if previous is None:
            os.environ.pop("STATE_DATABASE_URL", None)
        else:
            os.environ["STATE_DATABASE_URL"] = previous


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check or apply Hollawall inbox-review schema")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser


def main() -> None:
    args = _parser().parse_args()
    action = "apply" if args.apply else "check"
    dsn = _dsn()
    if not dsn:
        _emit({"action": action, "configured": False, "error": "database_not_configured", "ready": False})
        raise SystemExit(2)
    if args.apply and args.confirm != _CONFIRMATION:
        _emit({"action": action, "configured": True, "error": "confirmation_required", "ready": False})
        raise SystemExit(2)
    try:
        if args.apply:
            apply_migration(dsn)
        health = schema_health(dsn)
    except Exception as exc:
        _emit({"action": action, "configured": True, "error": type(exc).__name__, "ready": False})
        raise SystemExit(1) from None
    result = {"action": action, **health}
    _emit(result)
    if not bool(health.get("ready")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
