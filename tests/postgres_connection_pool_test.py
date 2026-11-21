from __future__ import annotations

import pytest

from services.postgres_connection_pool import (
    PostgresConnectionPool,
    PostgresPoolConfigurationError,
)


class FakeConnection:
    def __init__(self) -> None:
        self.autocommit = False
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakePool:
    check_connection = object()

    def __init__(self, conninfo: str, **kwargs) -> None:
        self.conninfo = conninfo
        self.kwargs = kwargs
        self.connection = FakeConnection()
        self.open_calls: list[tuple[bool, float]] = []
        self.getconn_calls: list[float] = []
        self.putconn_calls: list[FakeConnection] = []
        self.close_calls = 0

    def open(self, *, wait: bool, timeout: float) -> None:
        self.open_calls.append((wait, timeout))

    def getconn(self, *, timeout: float):
        self.getconn_calls.append(timeout)
        return self.connection

    def putconn(self, connection: FakeConnection) -> None:
        self.putconn_calls.append(connection)

    def close(self) -> None:
        self.close_calls += 1


class FakePoolFactory:
    check_connection = FakePool.check_connection

    def __init__(self) -> None:
        self.instances: list[FakePool] = []

    def __call__(self, conninfo: str, **kwargs) -> FakePool:
        pool = FakePool(conninfo, **kwargs)
        self.instances.append(pool)
        return pool


def test_pool_is_bounded_warmed_and_returns_raw_connections() -> None:
    factory = FakePoolFactory()
    provider = PostgresConnectionPool(
        "postgresql://pool-test",
        min_size=1,
        max_size=4,
        timeout=7.5,
        pool_factory=factory,
    )

    pool = factory.instances[0]
    assert pool.kwargs == {
        "min_size": 1,
        "max_size": 4,
        "timeout": 7.5,
        "open": False,
        "close_returns": True,
        "check": factory.check_connection,
    }

    provider.open()
    assert pool.open_calls == [(True, 7.5)]

    connection = provider.connect("postgresql://pool-test", autocommit=True)
    assert connection.raw is pool.connection
    assert connection.autocommit is True
    assert pool.getconn_calls == [7.5]
    connection.close()
    assert pool.putconn_calls == [pool.connection]

    second = provider.connect("postgresql://pool-test")
    assert second.raw is pool.connection
    assert second.autocommit is False
    assert pool.getconn_calls == [7.5, 7.5]
    with second:
        pass
    assert pool.connection.commits == 1
    assert pool.putconn_calls == [pool.connection, pool.connection]


def test_lease_rolls_back_and_returns_connection_on_context_error() -> None:
    factory = FakePoolFactory()
    provider = PostgresConnectionPool("postgresql://pool-test", pool_factory=factory)
    lease = provider.connect("postgresql://pool-test")

    with pytest.raises(RuntimeError):
        with lease:
            raise RuntimeError("rollback")

    raw = factory.instances[0].connection
    assert raw.rollbacks == 1
    assert factory.instances[0].putconn_calls == [raw]


def test_pool_rejects_cross_database_checkout_without_leaking_the_dsn() -> None:
    provider = PostgresConnectionPool(
        "postgresql://pool-test",
        pool_factory=FakePoolFactory(),
    )

    with pytest.raises(PostgresPoolConfigurationError) as captured:
        provider.connect("postgresql://different-test-database")

    assert "different-test-database" not in str(captured.value)
    assert "pool-test" not in str(captured.value)


def test_pool_configuration_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_DB_POOL_MIN_SIZE", "3")
    monkeypatch.setenv("DASHBOARD_DB_POOL_MAX_SIZE", "2")

    with pytest.raises(PostgresPoolConfigurationError, match="maximum"):
        PostgresConnectionPool.from_environment(
            "postgresql://pool-test",
            pool_factory=FakePoolFactory(),
        )

    monkeypatch.setenv("DASHBOARD_DB_POOL_MIN_SIZE", "not-an-int")
    monkeypatch.setenv("DASHBOARD_DB_POOL_MAX_SIZE", "4")
    with pytest.raises(PostgresPoolConfigurationError, match="integer"):
        PostgresConnectionPool.from_environment(
            "postgresql://pool-test",
            pool_factory=FakePoolFactory(),
        )


def test_pool_close_is_idempotent() -> None:
    factory = FakePoolFactory()
    provider = PostgresConnectionPool("postgresql://pool-test", pool_factory=factory)

    provider.close()
    provider.close()

    assert factory.instances[0].close_calls == 1


def test_registration_injects_one_open_pool_factory_into_every_runtime_repository(monkeypatch) -> None:
    from flask import Flask
    import dashboard_api
    from services import (
        canonical_dashboard_repository,
        canonical_finance,
        financial_debt_repository,
        financial_schema,
        financial_transaction_repository,
        interwallet_debt_service,
        project_document_repository,
    )

    pool = type("Pool", (), {"connect": lambda self, *_args, **_kwargs: None, "open": lambda self: None})()
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://pool-test")
    monkeypatch.setenv("CANONICAL_FINANCE_READS_ENABLED", "true")
    monkeypatch.setattr(dashboard_api, "PostgresConnectionPool", type("Provider", (), {
        "from_environment": classmethod(lambda cls, dsn: pool),
    }))
    monkeypatch.setattr(financial_schema, "verify_financial_schema", lambda _dsn: {"ready": True})

    observed: dict[str, object] = {}

    class Repository:
        def __init__(self, _dsn, *, connection_factory=None, **_kwargs):
            observed[self.__class__.__name__] = connection_factory

        def list_projects(self):
            return []

    class DashboardRepository(Repository):
        pass

    class ProjectDocumentRepository(Repository):
        pass

    class TransactionRepository(Repository):
        pass

    class DebtRepository(Repository):
        pass

    class CanonicalDashboardRepository(Repository):
        def registry(self):
            return {"wallets": [], "business_units": [], "opening_balances": [], "balance_adjustments": []}

    monkeypatch.setattr(dashboard_api, "DashboardRepository", DashboardRepository)
    monkeypatch.setattr(project_document_repository, "ProjectDocumentRepository", ProjectDocumentRepository)
    monkeypatch.setattr(financial_transaction_repository, "PostgresFinancialTransactionRepository", TransactionRepository)
    monkeypatch.setattr(financial_debt_repository, "PostgresInterwalletDebtRepository", DebtRepository)
    monkeypatch.setattr(canonical_dashboard_repository, "CanonicalDashboardRepository", CanonicalDashboardRepository)
    monkeypatch.setattr(canonical_finance, "CanonicalFinanceService", lambda repository: type("Transactions", (), {"list_effective_transactions": lambda self: []})())
    monkeypatch.setattr(interwallet_debt_service, "InterwalletDebtService", lambda repository: type("Debts", (), {"list_debts": lambda self: []})())

    app = Flask(__name__)
    dashboard_api.register_dashboard(app)

    assert app.extensions["postgres_connection_pool"] is pool
    assert set(observed) == {
        "DashboardRepository",
        "ProjectDocumentRepository",
        "TransactionRepository",
        "DebtRepository",
        "CanonicalDashboardRepository",
    }
    assert all(factory == pool.connect for factory in observed.values())
