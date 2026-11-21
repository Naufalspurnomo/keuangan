from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

from services.canonical_dashboard_repository import CanonicalDashboardRepository


NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)
WALLET_ID = UUID("00000000-0000-4000-8000-000000000201")
UNIT_ID = UUID("00000000-0000-4000-8000-000000000301")


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection
        self.query = ""

    def execute(self, query, _params=None) -> None:
        self.query = " ".join(str(query).split())
        self.connection.events.append(("execute", self.query))

    def fetchall(self):
        self.connection.events.append(("fetch", self.query))
        if "FROM wallets" in self.query:
            return [(WALLET_ID, "CV HB(101)")]
        if "FROM business_units" in self.query:
            return [(UNIT_ID, "HOLLA")]
        if "FROM wallet_opening_balances" in self.query:
            return [(WALLET_ID, UNIT_ID, 1_000_000, NOW)]
        if "FROM balance_adjustments" in self.query:
            return [(WALLET_ID, UNIT_ID, -100_000, NOW)]
        raise AssertionError(f"unexpected query: {self.query}")


class _Connection:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.pipeline_entries = 0
        self.closed = False

    @contextmanager
    def pipeline(self):
        self.pipeline_entries += 1
        yield object()

    def cursor(self):
        return _Cursor(self)

    def close(self) -> None:
        self.closed = True


def test_registry_uses_one_pipeline_round_trip_and_preserves_native_values() -> None:
    connection = _Connection()
    repository = CanonicalDashboardRepository(
        "postgresql://isolated-test",
        connection_factory=lambda _dsn: connection,
    )

    result = repository.registry()

    assert connection.pipeline_entries == 1
    assert [kind for kind, _query in connection.events[:4]] == ["execute"] * 4
    assert [kind for kind, _query in connection.events[4:]] == ["fetch"] * 4
    assert connection.closed is True
    assert result == {
        "wallets": [{"id": str(WALLET_ID), "display_name": "CV HB(101)"}],
        "business_units": [{"id": str(UNIT_ID), "legal_name": "HOLLA"}],
        "opening_balances": [{
            "wallet_id": str(WALLET_ID),
            "business_unit_id": str(UNIT_ID),
            "amount": 1_000_000,
            "effective_at": NOW,
        }],
        "balance_adjustments": [{
            "wallet_id": str(WALLET_ID),
            "business_unit_id": str(UNIT_ID),
            "delta_amount": -100_000,
            "effective_at": NOW,
        }],
    }


def test_registry_empty_results_remain_valid() -> None:
    class EmptyCursor(_Cursor):
        def fetchall(self):
            self.connection.events.append(("fetch", self.query))
            return []

    class EmptyConnection(_Connection):
        def cursor(self):
            return EmptyCursor(self)

    connection = EmptyConnection()
    result = CanonicalDashboardRepository(
        "postgresql://isolated-test",
        connection_factory=lambda _dsn: connection,
    ).registry()

    assert result == {
        "wallets": [],
        "business_units": [],
        "opening_balances": [],
        "balance_adjustments": [],
    }
    assert connection.closed is True
