"""Parameterized, read-only PostgreSQL access for the dashboard."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Optional

from dashboard_api.contracts import DashboardContractError, DashboardFilters


_TRANSACTION_COLUMNS = (
    "id",
    "source_key",
    "transaction_date",
    "amount",
    "transaction_type",
    "company",
    "wallet",
    "project",
    "category",
    "description",
    "recorded_by",
    "input_source",
    "source_wallet",
    "source_block",
    "is_valid",
    "updated_at",
)


@dataclass(frozen=True, slots=True)
class Page:
    items: list[dict[str, Any]]
    next_cursor: Optional[str]


def encode_cursor(transaction_date: date, item_id: int) -> str:
    payload = json.dumps(
        {"date": transaction_date.isoformat(), "id": int(item_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> tuple[date, int]:
    try:
        raw = str(value or "")
        padded = raw + ("=" * (-len(raw) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        marker_date = date.fromisoformat(payload["date"])
        item_id = int(payload["id"])
        if item_id <= 0:
            raise ValueError
        return marker_date, item_id
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise DashboardContractError("invalid cursor") from exc


class DashboardRepository:
    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise ValueError("dashboard repository requires a database DSN")
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory(self._dsn, autocommit=True)
        import psycopg

        return psycopg.connect(self._dsn, autocommit=True)

    def fetch_transactions(
        self,
        filters: DashboardFilters,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
        include_invalid: bool = False,
    ) -> Page:
        page_size = max(1, min(int(limit), 200))
        where = ["transaction_date >= %s", "transaction_date <= %s"]
        params: list[Any] = [filters.date_from, filters.date_to]
        if filters.wallet:
            where.append("wallet = %s")
            params.append(filters.wallet)
        if filters.company:
            where.append("company = %s")
            params.append(filters.company)
        if filters.project:
            where.append("project = %s")
            params.append(filters.project)
        if not include_invalid:
            where.append("is_valid = TRUE")
        if cursor:
            marker_date, marker_id = decode_cursor(cursor)
            where.append("(transaction_date, id) < (%s, %s)")
            params.extend((marker_date, marker_id))
        params.append(page_size + 1)
        sql = f"""
            SELECT {", ".join(_TRANSACTION_COLUMNS)}
            FROM financial_ledger
            WHERE {" AND ".join(where)}
            ORDER BY transaction_date DESC, id DESC
            LIMIT %s
        """
        with self._connect() as connection:
            with connection.cursor() as db_cursor:
                db_cursor.execute(sql, tuple(params))
                rows = db_cursor.fetchall()
        visible = rows[:page_size]
        items = [dict(zip(_TRANSACTION_COLUMNS, row)) for row in visible]
        next_cursor = None
        if len(rows) > page_size and visible:
            last = items[-1]
            next_cursor = encode_cursor(last["transaction_date"], last["id"])
        return Page(items=items, next_cursor=next_cursor)

    def fetch_filter_options(self) -> dict[str, list[str]]:
        sql = """
            SELECT DISTINCT wallet, company, project
            FROM financial_ledger
            WHERE wallet IS NOT NULL OR company IS NOT NULL OR project IS NOT NULL
            ORDER BY wallet, company, project
        """
        with self._connect() as connection:
            with connection.cursor() as db_cursor:
                db_cursor.execute(sql)
                rows = db_cursor.fetchall()
        return {
            "wallets": sorted({row[0] for row in rows if row[0]}),
            "companies": sorted({row[1] for row in rows if row[1]}),
            "projects": sorted({row[2] for row in rows if row[2]}),
        }

    def fetch_freshness(self) -> dict[str, Any]:
        sql = """
            SELECT MAX(updated_at), COUNT(*), COUNT(*) FILTER (WHERE NOT is_valid)
            FROM financial_ledger
        """
        with self._connect() as connection:
            with connection.cursor() as db_cursor:
                db_cursor.execute(sql)
                row = db_cursor.fetchone() or (None, 0, 0)
        return {
            "last_updated_at": row[0].isoformat() if isinstance(row[0], datetime) else None,
            "row_count": int(row[1] or 0),
            "invalid_count": int(row[2] or 0),
        }
