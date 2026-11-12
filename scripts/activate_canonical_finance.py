#!/usr/bin/env python3
"""One-way fresh-zero PostgreSQL finance activation gate for production startup."""

from __future__ import annotations

import hashlib
import os

from services.financial_schema import (
    MIGRATION_LOCK_ID,
    apply_financial_migrations,
    load_production_bootstrap_migrations,
)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_BUSINESS_TABLES = (
    "projects",
    "project_scopes",
    "project_documents",
    "project_document_lines",
    "project_document_allocations",
    "project_transaction_evidence",
    "project_quotation_handoffs",
    "financial_transactions",
    "financial_postings",
    "wallet_opening_balances",
    "balance_adjustments",
    "project_status_events",
    "interwallet_debts",
    "interwallet_debt_events",
    "financial_export_outbox",
    "financial_command_quarantine",
)


def _enabled(name: str) -> bool:
    return str(os.getenv(name) or "").strip().casefold() in _TRUE_VALUES


def _dsn() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def activate() -> None:
    if not _enabled("CANONICAL_FINANCE_ACTIVATE"):
        return
    dsn = _dsn()
    if not dsn:
        raise RuntimeError("canonical finance activation requires a database DSN")

    apply_financial_migrations(
        dsn,
        migrations=load_production_bootstrap_migrations(),
    )

    import psycopg

    release = str(os.getenv("RELEASE_SHA") or os.getenv("KOYEB_GIT_SHA") or "unknown").strip()
    evidence = hashlib.sha256(
        f"hollawall:finance-authority:postgresql:fresh-zero:v1:{release}".encode()
    ).hexdigest()
    lock_targets = ", ".join(_BUSINESS_TABLES)

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
        cursor.execute(f"LOCK TABLE {lock_targets} IN ACCESS EXCLUSIVE MODE")
        counts: dict[str, int] = {}
        for table in _BUSINESS_TABLES:
            cursor.execute(f"SELECT count(*) FROM {table}")
            count_row = cursor.fetchone()
            if count_row is None:
                raise RuntimeError(f"canonical finance row-count readback failed: {table}")
            counts[table] = int(count_row[0])

        cursor.execute(
            """
            SELECT authority, historical_import, activated_at,
                   activated_by, activation_evidence_sha256
              FROM finance_authority_state
             WHERE singleton = TRUE
             FOR UPDATE
            """
        )
        state = cursor.fetchone()
        if state is None:
            raise RuntimeError("canonical finance authority latch is missing")
        authority = str(state[0])
        historical_import = bool(state[1])
        if historical_import:
            raise RuntimeError("historical finance import is forbidden")

        nonzero = {table: count for table, count in counts.items() if count}
        if authority == "google_sheets":
            if nonzero:
                raise RuntimeError(
                    "canonical finance activation requires fresh-zero business tables"
                )
            cursor.execute(
                """
                UPDATE finance_authority_state
                   SET authority = 'postgresql',
                       activated_at = now(),
                       activated_by = %s,
                       activation_evidence_sha256 = %s
                 WHERE singleton = TRUE AND authority = 'google_sheets'
                """,
                (f"release:{release}", evidence),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("canonical finance authority activation lost its lock")
        elif authority == "postgresql":
            if state[2] is None or not str(state[3] or "").strip() or not str(state[4] or "").strip():
                raise RuntimeError("canonical finance authority evidence is incomplete")
        else:
            raise RuntimeError("canonical finance authority latch is invalid")

        cursor.execute(
            """
            SELECT authority, historical_import
              FROM finance_authority_state
             WHERE singleton = TRUE
            """
        )
        readback = cursor.fetchone()
        if readback != ("postgresql", False):
            raise RuntimeError("canonical finance authority readback failed")
        connection.commit()


if __name__ == "__main__":
    activate()
