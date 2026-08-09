"""Durable Postgres read-model for the financial ledger.

Google Sheets remains the compatibility ledger during the migration.  Every
successful Sheet write is mirrored here using a deterministic source key, so a
retry or a historical re-import cannot create a second financial record.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from security import secure_log
from utils.amounts import parse_money_token
from utils.parsers import parse_revision_amount


_INIT_LOCK = threading.Lock()
_INITIALIZED_DSN: Optional[str] = None


def _database_url() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _enabled() -> bool:
    """Allow an explicit opt-out, but enable the mirror with production Postgres."""
    configured = str(os.getenv("LEDGER_STORE_BACKEND", "")).strip().lower()
    return configured not in {"off", "none", "local", "disabled"} and bool(_database_url())


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _parse_amount(value: Any) -> int:
    raw = str(value or "").strip()
    if raw and re.search(r"(?:rb|ribu|k|jt|juta|perak)\b", raw, re.IGNORECASE):
        try:
            return abs(parse_revision_amount(raw))
        except (TypeError, ValueError):
            return 0
    return abs(parse_money_token(value))


def _source_row(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _canonical_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the source evidence JSON serializable and bounded."""
    return {
        str(key): value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in row.items()
        if value is None or isinstance(value, (str, int, float, bool, date, datetime, list, dict))
    }


def build_source_key(row: Dict[str, Any]) -> str:
    """Stable idempotency key for a Sheet row or a live bot event."""
    sheet_name = _clean(row.get("sheet_name") or row.get("dompet_sheet"), 160)
    source_block = _clean(row.get("source_block"), 40).lower() or "ledger"
    message_id = _clean(row.get("message_id"), 240)
    if message_id:
        return f"message:{sheet_name}:{source_block}:{message_id}"

    # Historic manual rows have no event id.  Row number keeps intentional
    # duplicates distinct while the content hash catches a changed import input.
    source_row = _source_row(row.get("sheet_row"))
    identity = {
        "sheet": sheet_name,
        "block": source_block,
        "row": source_row,
        "tanggal": _clean(row.get("tanggal"), 40),
        "jumlah": _clean(row.get("jumlah"), 80),
        "keterangan": _clean(row.get("keterangan"), 500),
        "project": _clean(row.get("nama_projek"), 160),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"sheet:{sheet_name}:{source_block}:{source_row}:{digest}"


def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map the mixed Sheet layouts into one durable ledger record."""
    source_sheet = _clean(row.get("sheet_name") or row.get("dompet_sheet"), 160)
    source_block = _clean(row.get("source_block"), 40).lower() or "ledger"
    amount = _parse_amount(row.get("jumlah", row.get("amount", 0)))
    transaction_type = _clean(row.get("tipe"), 24) or "Pengeluaran"
    payload = _canonical_payload(row)
    normalized = {
        "source_key": build_source_key(row),
        "source_sheet": source_sheet,
        "source_row": _source_row(row.get("sheet_row")) or None,
        "source_block": source_block,
        "message_id": _clean(row.get("message_id"), 240) or None,
        "transaction_date": _parse_date(row.get("tanggal")),
        "amount": amount if amount > 0 else None,
        "transaction_type": transaction_type,
        "company": _clean(row.get("company") or row.get("company_sheet"), 160) or None,
        "wallet": _clean(row.get("dompet_sheet") or source_sheet, 160) or None,
        "project": _clean(row.get("nama_projek"), 160) or None,
        "category": _clean(row.get("kategori"), 120) or None,
        "description": _clean(row.get("keterangan"), 1000) or None,
        "recorded_by": _clean(row.get("oleh") or row.get("sender_name"), 160) or None,
        "input_source": _clean(row.get("source"), 80) or None,
        "source_wallet": _clean(row.get("source_wallet"), 160) or None,
        "is_valid": bool(amount > 0 and _parse_date(row.get("tanggal"))),
        "payload": payload,
    }
    return normalized


def _ensure_table() -> bool:
    global _INITIALIZED_DSN
    dsn = _database_url()
    if not _enabled():
        return False
    if _INITIALIZED_DSN == dsn:
        return True
    with _INIT_LOCK:
        if _INITIALIZED_DSN == dsn:
            return True
        import psycopg

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS financial_ledger (
                        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        source_key TEXT NOT NULL UNIQUE,
                        source_sheet TEXT NOT NULL,
                        source_row INTEGER,
                        source_block TEXT NOT NULL,
                        message_id TEXT,
                        transaction_date DATE,
                        amount BIGINT,
                        transaction_type TEXT NOT NULL,
                        company TEXT,
                        wallet TEXT,
                        project TEXT,
                        category TEXT,
                        description TEXT,
                        recorded_by TEXT,
                        input_source TEXT,
                        source_wallet TEXT,
                        is_valid BOOLEAN NOT NULL DEFAULT TRUE,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_financial_ledger_date ON financial_ledger (transaction_date DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_financial_ledger_wallet_date ON financial_ledger (wallet, transaction_date DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_financial_ledger_project ON financial_ledger (project) WHERE project IS NOT NULL"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_financial_ledger_message ON financial_ledger (message_id) WHERE message_id IS NOT NULL"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS financial_ledger_import_runs (
                        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        source TEXT NOT NULL,
                        rows_seen INTEGER NOT NULL,
                        rows_upserted INTEGER NOT NULL,
                        invalid_rows INTEGER NOT NULL,
                        completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS financial_projects (
                        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        project_key TEXT NOT NULL UNIQUE,
                        project TEXT NOT NULL,
                        wallet TEXT,
                        company TEXT,
                        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_financial_projects_lookup ON financial_projects (project, wallet)"
                )
        _INITIALIZED_DSN = dsn
        secure_log("INFO", "Durable Postgres financial ledger ready")
    return True


def upsert_row(row: Dict[str, Any]) -> bool:
    """Mirror one successful Sheet row.  Never turns a Sheets success into a failure."""
    if not _ensure_table():
        return False
    try:
        import psycopg
        from psycopg.types.json import Jsonb

        values = normalize_row(row)
        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO financial_ledger (
                        source_key, source_sheet, source_row, source_block, message_id,
                        transaction_date, amount, transaction_type, company, wallet,
                        project, category, description, recorded_by, input_source,
                        source_wallet, is_valid, payload
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (source_key) DO UPDATE SET
                        source_sheet = EXCLUDED.source_sheet,
                        source_row = EXCLUDED.source_row,
                        source_block = EXCLUDED.source_block,
                        message_id = EXCLUDED.message_id,
                        transaction_date = EXCLUDED.transaction_date,
                        amount = EXCLUDED.amount,
                        transaction_type = EXCLUDED.transaction_type,
                        company = EXCLUDED.company,
                        wallet = EXCLUDED.wallet,
                        project = EXCLUDED.project,
                        category = EXCLUDED.category,
                        description = EXCLUDED.description,
                        recorded_by = EXCLUDED.recorded_by,
                        input_source = EXCLUDED.input_source,
                        source_wallet = EXCLUDED.source_wallet,
                        is_valid = EXCLUDED.is_valid,
                        payload = EXCLUDED.payload,
                        updated_at = NOW()
                    """,
                    (
                        values["source_key"], values["source_sheet"], values["source_row"], values["source_block"],
                        values["message_id"], values["transaction_date"], values["amount"], values["transaction_type"],
                        values["company"], values["wallet"], values["project"], values["category"], values["description"],
                        values["recorded_by"], values["input_source"], values["source_wallet"], values["is_valid"],
                        Jsonb(values["payload"]),
                    ),
                )
                _upsert_project_with_cursor(cur, values)
        return True
    except Exception as exc:
        secure_log("ERROR", f"Financial ledger mirror failed: {type(exc).__name__}: {exc}")
        return False


def import_rows(rows: Iterable[Dict[str, Any]], source: str = "google_sheets") -> Dict[str, int]:
    """Upsert a complete historical snapshot and record one auditable import run."""
    materialized = list(rows)
    if not _ensure_table():
        raise RuntimeError("Financial ledger requires STATE_DATABASE_URL")

    import psycopg
    from psycopg.types.json import Jsonb

    columns = (
        "source_key, source_sheet, source_row, source_block, message_id, transaction_date, amount, "
        "transaction_type, company, wallet, project, category, description, recorded_by, input_source, "
        "source_wallet, is_valid, payload"
    )
    assignments = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns.split(", ")
        if column != "source_key"
    )
    statement = f"""
        INSERT INTO financial_ledger ({columns}) VALUES ({", ".join(["%s"] * 18)})
        ON CONFLICT (source_key) DO UPDATE SET {assignments}, updated_at = NOW()
    """
    normalized_rows = [normalize_row(row) for row in materialized]
    invalid = sum(1 for row in normalized_rows if not row["is_valid"])
    with psycopg.connect(_database_url()) as conn:
        with conn.cursor() as cur:
            for values in normalized_rows:
                cur.execute(
                    statement,
                    (
                        values["source_key"], values["source_sheet"], values["source_row"], values["source_block"],
                        values["message_id"], values["transaction_date"], values["amount"], values["transaction_type"],
                        values["company"], values["wallet"], values["project"], values["category"], values["description"],
                        values["recorded_by"], values["input_source"], values["source_wallet"], values["is_valid"],
                        Jsonb(values["payload"]),
                    ),
                )
                _upsert_project_with_cursor(cur, values)
        conn.commit()
    with psycopg.connect(_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO financial_ledger_import_runs (source, rows_seen, rows_upserted, invalid_rows)
                VALUES (%s, %s, %s, %s)
                """,
                (source, len(materialized), len(normalized_rows), invalid),
            )
    return {"rows_seen": len(materialized), "rows_upserted": len(normalized_rows), "invalid_rows": invalid}


def _project_key(project: str, wallet: str, company: str) -> str:
    identity = "|".join((project.strip().lower(), wallet.strip().lower(), company.strip().lower()))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _upsert_project_with_cursor(cursor, values: Dict[str, Any]) -> None:
    project = str(values.get("project") or "").strip()
    if not project:
        return
    wallet = str(values.get("wallet") or "").strip()
    company = str(values.get("company") or "").strip()
    cursor.execute(
        """
        INSERT INTO financial_projects (project_key, project, wallet, company)
        VALUES (%s, %s, NULLIF(%s, ''), NULLIF(%s, ''))
        ON CONFLICT (project_key) DO UPDATE SET
            project = EXCLUDED.project, wallet = EXCLUDED.wallet,
            company = EXCLUDED.company, last_seen_at = NOW()
        """,
        (_project_key(project, wallet, company), project, wallet, company),
    )


def import_projects(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Seed a compact project index from all Sheets history, independent of retention."""
    materialized = [normalize_row(row) for row in rows]
    if not _ensure_table():
        raise RuntimeError("Financial project index requires STATE_DATABASE_URL")
    seen = set()
    inserted = 0
    import psycopg
    with psycopg.connect(_database_url()) as conn:
        with conn.cursor() as cur:
            for values in materialized:
                project = str(values.get("project") or "").strip()
                if not project:
                    continue
                dedup_key = _project_key(project, str(values.get("wallet") or ""), str(values.get("company") or ""))
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                _upsert_project_with_cursor(cur, values)
                inserted += 1
        conn.commit()
    return {"projects_seen": len(seen), "projects_upserted": inserted}


def get_status() -> Dict[str, Any]:
    """Expose only safe health metadata for deployment verification."""
    if not _ensure_table():
        return {"backend": "disabled", "count": 0, "invalid": 0}
    import psycopg

    with psycopg.connect(_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE NOT is_valid) FROM financial_ledger")
            count, invalid = cur.fetchone()
    return {"backend": "postgres", "count": int(count), "invalid": int(invalid)}


def import_completed(source: str) -> bool:
    """Whether this exact bootstrap/import source already completed successfully."""
    if not _ensure_table():
        return False
    import psycopg
    with psycopg.connect(_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM financial_ledger_import_runs WHERE source = %s)",
                (source,),
            )
            return bool(cur.fetchone()[0])


def try_import_lock(source: str):
    """Return a session holding a Postgres advisory lock, or None when another replica owns it."""
    if not _ensure_table():
        return None
    import psycopg
    connection = psycopg.connect(_database_url(), autocommit=True)
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (f"ledger-import:{source}",))
            if not cur.fetchone()[0]:
                connection.close()
                return None
        return connection
    except Exception:
        connection.close()
        raise


def read_backend_enabled() -> bool:
    return str(os.getenv("LEDGER_READ_BACKEND", "")).strip().lower() in {"postgres", "postgresql"}


def read_recent_transactions(days: int) -> Optional[List[Dict[str, Any]]]:
    """Return dashboard-compatible transactions, or None to retain Sheets fallback."""
    if not read_backend_enabled() or not _ensure_table():
        return None
    try:
        import psycopg

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT transaction_date, description, amount, transaction_type, recorded_by,
                           category, company, project, source_sheet, source_row
                    FROM financial_ledger
                    WHERE is_valid
                      AND (%s <= 0 OR transaction_date >= CURRENT_DATE - %s)
                    ORDER BY transaction_date DESC, id DESC
                    """,
                    (int(days or 0), max(0, int(days or 0))),
                )
                rows = cur.fetchall()
        # A blank database is not authoritative.  This prevents an early flag
        # change from hiding the existing Sheets ledger before the first import.
        if not rows:
            return None
        return [
            {
                "tanggal": value[0].isoformat() if value[0] else "",
                "keterangan": value[1] or "",
                "jumlah": int(value[2] or 0),
                "tipe": value[3] or "Pengeluaran",
                "oleh": value[4] or "",
                "kategori": value[5] or "Lain-lain",
                "company_sheet": value[6] or "",
                "nama_projek": value[7] or "",
                "sheet_name": value[8] or "",
                "sheet_row": value[9],
            }
            for value in rows
        ]
    except Exception as exc:
        secure_log("ERROR", f"Financial ledger read failed; falling back to Sheets: {type(exc).__name__}: {exc}")
        return None


def read_project_records() -> Optional[List[Dict[str, str]]]:
    """Return the project index after a validated import, otherwise signal fallback."""
    if not read_backend_enabled() or not _ensure_table():
        return None
    try:
        import psycopg

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project, wallet, company
                    FROM financial_projects
                    WHERE LENGTH(TRIM(project)) > 2
                    ORDER BY project, wallet
                    """
                )
                rows = cur.fetchall()
        if not rows:
            return None
        return [
            {"name": row[0], "dompet": row[1] or "", "company": row[2] or ""}
            for row in rows
        ]
    except Exception as exc:
        secure_log("ERROR", f"Financial project index read failed; falling back to Sheets: {type(exc).__name__}: {exc}")
        return None


def update_amount_by_source(source_sheet: str, source_row: int, source_block: str, amount: Any) -> bool:
    """Keep revision edits mirrored without allowing a mirror failure to break Sheets."""
    if not _ensure_table():
        return False
    parsed = parse_money_token(amount)
    try:
        import psycopg
        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE financial_ledger
                    SET amount = %s, is_valid = (%s IS NOT NULL) AND transaction_date IS NOT NULL,
                        updated_at = NOW()
                    WHERE source_sheet = %s AND source_row = %s AND source_block = %s
                    """,
                    (parsed if parsed > 0 else None, parsed if parsed > 0 else None, source_sheet, int(source_row), source_block),
                )
        return True
    except Exception as exc:
        secure_log("ERROR", f"Financial ledger amount mirror failed: {type(exc).__name__}: {exc}")
        return False


def delete_by_source(source_sheet: str, source_row: int, source_block: Optional[str] = None) -> bool:
    """Mirror an explicit Sheet deletion; this is never called for ordinary imports."""
    if not _ensure_table():
        return False
    try:
        import psycopg
        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                if source_block:
                    cur.execute(
                        "DELETE FROM financial_ledger WHERE source_sheet = %s AND source_row = %s AND source_block = %s",
                        (source_sheet, int(source_row), source_block),
                    )
                else:
                    cur.execute(
                        "DELETE FROM financial_ledger WHERE source_sheet = %s AND source_row = %s",
                        (source_sheet, int(source_row)),
                    )
        return True
    except Exception as exc:
        secure_log("ERROR", f"Financial ledger deletion mirror failed: {type(exc).__name__}: {exc}")
        return False


def reset_ledger_store_for_tests() -> None:
    global _INITIALIZED_DSN
    _INITIALIZED_DSN = None
