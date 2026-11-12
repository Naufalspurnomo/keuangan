"""Read-only PostgreSQL source for the fresh canonical finance dashboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class CanonicalDashboardRepository:
    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise ValueError("canonical dashboard repository requires a database DSN")
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory(self._dsn)
        import psycopg

        return psycopg.connect(self._dsn)

    def registry(self) -> dict[str, list[dict[str, Any]]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, display_name FROM wallets WHERE active = TRUE ORDER BY code"
                )
                wallets = [
                    {"id": str(row[0]), "display_name": str(row[1])}
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    "SELECT id, legal_name FROM business_units WHERE active = TRUE ORDER BY code"
                )
                units = [
                    {"id": str(row[0]), "legal_name": str(row[1])}
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    SELECT wallet_id, business_unit_id, amount, effective_at
                    FROM wallet_opening_balances
                    ORDER BY effective_at, id
                    """
                )
                openings = [
                    {
                        "wallet_id": str(row[0]),
                        "business_unit_id": str(row[1]),
                        "amount": int(row[2]),
                        "effective_at": row[3],
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    SELECT wallet_id, business_unit_id, delta_amount, effective_at
                    FROM balance_adjustments
                    ORDER BY effective_at, id
                    """
                )
                adjustments = [
                    {
                        "wallet_id": str(row[0]),
                        "business_unit_id": str(row[1]),
                        "delta_amount": int(row[2]),
                        "effective_at": row[3],
                    }
                    for row in cursor.fetchall()
                ]
        finally:
            connection.close()
        return {
            "wallets": wallets,
            "business_units": units,
            "opening_balances": openings,
            "balance_adjustments": adjustments,
        }
