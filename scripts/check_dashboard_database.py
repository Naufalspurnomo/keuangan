#!/usr/bin/env python3
"""Sanitized provider/readiness gate for the Hollawall dashboard."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True, slots=True)
class ProviderReport:
    connected: bool
    postgres_version: Optional[str]
    ssl_in_use: Optional[bool]
    ledger_access: bool
    ledger_rows: int
    invalid_rows: int
    last_import_at: Optional[str]
    read_only_session: Optional[bool]
    provider: str
    error: Optional[str] = None


def _provider_name(dsn: str) -> str:
    lowered = dsn.lower()
    if "supabase" in lowered:
        return "supabase"
    if "neon" in lowered:
        return "neon"
    if "railway" in lowered:
        return "railway"
    if "render" in lowered:
        return "render"
    if "koyeb" in lowered:
        return "koyeb"
    return "external-postgresql"


def check_provider(
    dsn: str,
    *,
    connection_factory: Optional[Callable[..., Any]] = None,
) -> ProviderReport:
    sanitized_provider = _provider_name(str(dsn or ""))
    if not str(dsn or "").strip():
        return ProviderReport(False, None, None, False, 0, 0, None, None, sanitized_provider, "database DSN missing")
    try:
        if connection_factory is None:
            import psycopg

            connection_factory = psycopg.connect
        with connection_factory(dsn, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('server_version'), pg_is_in_recovery(), "
                    "current_setting('transaction_read_only'), "
                    "CASE WHEN ssl_is_used() THEN TRUE ELSE FALSE END"
                )
                version, _recovery, read_only, ssl_used = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*), COUNT(*) FILTER (WHERE NOT is_valid), MAX(updated_at) "
                    "FROM financial_ledger"
                )
                count, invalid, _ledger_updated = cursor.fetchone()
                cursor.execute("SELECT MAX(completed_at) FROM financial_ledger_import_runs")
                import_row = cursor.fetchone()
        last_import = import_row[0].isoformat() if import_row and import_row[0] else None
        return ProviderReport(
            True,
            str(version),
            bool(ssl_used),
            True,
            int(count or 0),
            int(invalid or 0),
            last_import,
            str(read_only).lower() == "on",
            sanitized_provider,
        )
    except Exception as exc:
        return ProviderReport(
            False,
            None,
            None,
            False,
            0,
            0,
            None,
            None,
            sanitized_provider,
            type(exc).__name__,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn-env", default="STATE_DATABASE_URL")
    args = parser.parse_args()
    dsn = str(os.getenv(args.dsn_env) or os.getenv("DATABASE_URL") or "").strip()
    report = check_provider(dsn)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0 if report.connected and report.ledger_access else 1


if __name__ == "__main__":
    raise SystemExit(main())
