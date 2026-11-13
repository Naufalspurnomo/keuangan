from __future__ import annotations

from flask import Flask

from dashboard_api import register_dashboard
from services.financial_debt_repository import PostgresInterwalletDebtRepository


class RecordingCursor:
    def __init__(self, fetchone_values=None):
        self.executed = []
        self._fetchone = list(fetchone_values or [])

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class RecordingConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def debt_and_event():
    debt = {
        "id": "10000000-0000-4000-8000-000000000001",
        "lender_wallet_id": "20000000-0000-4000-8000-000000000001",
        "borrower_wallet_id": "20000000-0000-4000-8000-000000000002",
        "lender_business_unit_id": "30000000-0000-4000-8000-000000000001",
        "borrower_business_unit_id": "30000000-0000-4000-8000-000000000002",
        "project_id": None,
        "principal": 1_000_000,
        "currency": "IDR",
        "occurred_at": "2026-11-11T10:00:00+00:00",
        "due_at": None,
        "description": "Dana talangan internal",
        "actor": {"id": "boss", "role": "boss", "channel": "dashboard"},
    }
    event = {
        "id": "40000000-0000-4000-8000-000000000001",
        "debt_id": debt["id"],
        "event_type": "disbursement",
        "amount": debt["principal"],
        "occurred_at": debt["occurred_at"],
        "actor": debt["actor"],
        "description": None,
        "reason": None,
        "corrects_event_id": None,
        "reverses_event_id": None,
        "corrected_event_type": None,
        "postings": [
            {"id": "50000000-0000-4000-8000-000000000001", "wallet_id": debt["lender_wallet_id"], "business_unit_id": debt["lender_business_unit_id"], "account_class": "cash", "signed_amount": -1_000_000, "currency": "IDR"},
            {"id": "50000000-0000-4000-8000-000000000002", "wallet_id": debt["borrower_wallet_id"], "business_unit_id": debt["borrower_business_unit_id"], "account_class": "cash", "signed_amount": 1_000_000, "currency": "IDR"},
            {"id": "50000000-0000-4000-8000-000000000003", "wallet_id": None, "business_unit_id": debt["lender_business_unit_id"], "account_class": "receivable", "signed_amount": 1_000_000, "currency": "IDR"},
            {"id": "50000000-0000-4000-8000-000000000004", "wallet_id": None, "business_unit_id": debt["borrower_business_unit_id"], "account_class": "payable", "signed_amount": -1_000_000, "currency": "IDR"},
        ],
    }
    return debt, event


def outbox(debt_id):
    return {
        "id": "60000000-0000-4000-8000-000000000001",
        "export_key": f"debt:{debt_id}:1",
        "payload": {"debt_id": debt_id, "version": 1},
        "payload_sha256": "a" * 64,
    }


def test_create_persists_internal_transaction_postings_event_and_outbox_atomically():
    cursor = RecordingCursor([None])
    connection = RecordingConnection(cursor)
    repository = PostgresInterwalletDebtRepository(
        "postgresql://isolated-test",
        connection_factory=lambda _dsn: connection,
    )
    debt, event = debt_and_event()

    result = repository.create(
        debt,
        event,
        idempotency_key_hash="b" * 64,
        request_hash="c" * 64,
        outbox=outbox(debt["id"]),
    )

    sql = [statement for statement, _params in cursor.executed]
    assert result == (debt["id"], False)
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert next(i for i, item in enumerate(sql) if "INSERT INTO financial_transactions" in item) < next(i for i, item in enumerate(sql) if "INSERT INTO interwallet_debt_events" in item)
    assert sum("INSERT INTO financial_postings" in item for item in sql) == 4
    assert any("INSERT INTO financial_export_outbox" in item for item in sql)
    transaction_params = next(params for statement, params in cursor.executed if "INSERT INTO financial_transactions" in statement)
    assert transaction_params[0] == event["id"]
    transaction_sql = next(statement for statement, _params in cursor.executed if "INSERT INTO financial_transactions" in statement)
    assert "'internal', NULL, 'transfer', 'internal'" in transaction_sql


def test_create_replays_same_idempotency_key_without_new_writes():
    debt, event = debt_and_event()
    cursor = RecordingCursor([(debt["id"], event["id"], "c" * 64)])
    connection = RecordingConnection(cursor)
    repository = PostgresInterwalletDebtRepository(
        "postgresql://isolated-test",
        connection_factory=lambda _dsn: connection,
    )

    result = repository.create(
        debt,
        event,
        idempotency_key_hash="b" * 64,
        request_hash="c" * 64,
        outbox=outbox(debt["id"]),
    )

    assert result == (debt["id"], True)
    assert connection.commits == 1
    assert not any("INSERT INTO" in statement for statement, _params in cursor.executed)


def test_append_rejects_stale_version_under_debt_row_lock():
    debt, event = debt_and_event()
    debt_row = tuple(debt.get(key) for key in PostgresInterwalletDebtRepository._DEBT_COLUMNS)
    cursor = RecordingCursor([None, debt_row, (2,)])
    connection = RecordingConnection(cursor)
    repository = PostgresInterwalletDebtRepository(
        "postgresql://isolated-test",
        connection_factory=lambda _dsn: connection,
    )

    try:
        repository.append_event(
            debt["id"], event, expected_version=1,
            idempotency_key_hash="b" * 64, request_hash="c" * 64,
            outbox=outbox(debt["id"]),
        )
    except Exception as error:
        assert "version changed concurrently" in str(error)
    else:
        raise AssertionError("stale expected_version must fail")

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert any("FOR UPDATE" in statement for statement, _params in cursor.executed)


def test_create_rolls_back_every_record_when_one_write_fails():
    class FailingCursor(RecordingCursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "INSERT INTO interwallet_debt_events" in str(sql):
                raise RuntimeError("event insert failed")

    cursor = FailingCursor([None])
    connection = RecordingConnection(cursor)
    repository = PostgresInterwalletDebtRepository(
        "postgresql://isolated-test",
        connection_factory=lambda _dsn: connection,
    )
    debt, event = debt_and_event()

    try:
        repository.create(debt, event, idempotency_key_hash="b" * 64, request_hash="c" * 64, outbox=outbox(debt["id"]))
    except RuntimeError as error:
        assert str(error) == "event insert failed"
    else:
        raise AssertionError("repository must propagate persistence failure")

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed == 1


def test_postgres_transaction_readback_restores_authority_ids_from_postings():
    from services.financial_transaction_repository import PostgresFinancialTransactionRepository

    wallet_id = "00000000-0000-4000-8000-000000000701"
    business_unit_id = "00000000-0000-4000-8000-000000000702"
    record_row = tuple(
        {
            "id": "00000000-0000-4000-8000-000000000703",
            "scope": "project",
            "project_id": "00000000-0000-4000-8000-000000000704",
            "transaction_type": "inflow",
            "flow_class": "project_income",
            "amount": 1000,
            "currency": "IDR",
            "category": "Lain-lain",
            "description": "Readback",
            "occurred_at": "2026-11-13T00:00:00+07:00",
            "source": "dashboard",
            "source_reference": "dashboard-api:test",
            "evidence": {},
            "actor": {"id": "boss@example.com", "email": "boss@example.com", "role": "boss"},
            "revision_of_id": None,
            "reversal_of_id": None,
            "version": 1,
            "status": "posted",
            "created_at": "2026-11-13T00:00:00+00:00",
        }[column]
        for column in PostgresFinancialTransactionRepository._RECORD_COLUMNS
    )

    class Cursor:
        def __init__(self):
            self.calls = 0

        def execute(self, _query, _params):
            self.calls += 1

        def fetchone(self):
            return record_row

        def fetchall(self):
            return [
                (
                    "00000000-0000-4000-8000-000000000705",
                    wallet_id,
                    business_unit_id,
                    "cash",
                    1000,
                    "IDR",
                )
            ]

    repository = object.__new__(PostgresFinancialTransactionRepository)
    record = repository._read_record(Cursor(), record_row[0])

    assert record["wallet_id"] == wallet_id
    assert record["business_unit_id"] == business_unit_id


def test_canonical_blueprints_are_dormant_without_explicit_flag(monkeypatch):
    monkeypatch.delenv("CANONICAL_FINANCE_API_ENABLED", raising=False)
    monkeypatch.delenv("CANONICAL_FINANCE_WRITES_ENABLED", raising=False)
    app = Flask(__name__)
    register_dashboard(app, repository=object(), canonical_transaction_service=object(), canonical_debt_service=object())
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert not any(rule.startswith("/api/dashboard/v1/canonical-transactions") for rule in rules)
    assert not any(rule.startswith("/api/dashboard/v1/debts") for rule in rules)


def test_register_dashboard_hydrates_empty_actor_assertion_config_from_environment(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ACTOR_ASSERTION_SECRET", "s" * 64)
    monkeypatch.setenv("DASHBOARD_ACTOR_ASSERTION_AUDIENCE", "runtime-audience")
    app = Flask(__name__)
    app.config["DASHBOARD_ACTOR_ASSERTION_SECRET"] = ""
    app.config["DASHBOARD_ACTOR_ASSERTION_AUDIENCE"] = ""

    register_dashboard(app, repository=object())

    assert app.config["DASHBOARD_ACTOR_ASSERTION_SECRET"] == "s" * 64
    assert app.config["DASHBOARD_ACTOR_ASSERTION_AUDIENCE"] == "runtime-audience"


def test_register_dashboard_preserves_explicit_actor_assertion_config(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ACTOR_ASSERTION_SECRET", "e" * 64)
    monkeypatch.setenv("DASHBOARD_ACTOR_ASSERTION_AUDIENCE", "env-audience")
    app = Flask(__name__)
    app.config["DASHBOARD_ACTOR_ASSERTION_SECRET"] = "x" * 64
    app.config["DASHBOARD_ACTOR_ASSERTION_AUDIENCE"] = "explicit-audience"

    register_dashboard(app, repository=object())

    assert app.config["DASHBOARD_ACTOR_ASSERTION_SECRET"] == "x" * 64
    assert app.config["DASHBOARD_ACTOR_ASSERTION_AUDIENCE"] == "explicit-audience"


def test_canonical_blueprints_register_only_with_explicit_flag_and_durable_services(monkeypatch):
    monkeypatch.setenv("CANONICAL_FINANCE_API_ENABLED", "true")
    app = Flask(__name__)
    register_dashboard(app, repository=object(), canonical_transaction_service=object(), canonical_debt_service=object())
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/dashboard/v1/canonical-transactions" in rules
    assert "/api/dashboard/v1/debts" in rules


def test_canonical_flag_fails_closed_without_dsn_or_injected_services(monkeypatch):
    monkeypatch.setenv("CANONICAL_FINANCE_API_ENABLED", "true")
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    try:
        register_dashboard(Flask(__name__), repository=object())
    except RuntimeError as error:
        assert "database DSN" in str(error)
    else:
        raise AssertionError("canonical activation without durable storage must fail closed")


def test_canonical_flag_builds_postgres_services_after_schema_verification(monkeypatch):
    from services import canonical_finance, financial_debt_repository, financial_schema
    from services import financial_transaction_repository, interwallet_debt_service

    monkeypatch.setenv("CANONICAL_FINANCE_API_ENABLED", "true")
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://isolated-test")
    verified = []
    monkeypatch.setattr(financial_schema, "verify_financial_schema", lambda dsn: verified.append(dsn) or {"ready": True})
    monkeypatch.setattr(financial_transaction_repository, "PostgresFinancialTransactionRepository", lambda dsn: ("transactions", dsn))
    monkeypatch.setattr(financial_debt_repository, "PostgresInterwalletDebtRepository", lambda dsn: ("debts", dsn))
    monkeypatch.setattr(canonical_finance, "CanonicalFinanceService", lambda repository: ("transaction-service", repository))
    monkeypatch.setattr(interwallet_debt_service, "InterwalletDebtService", lambda repository: ("debt-service", repository))

    app = Flask(__name__)
    register_dashboard(app, repository=object())

    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert verified == ["postgresql://isolated-test"]
    assert "/api/dashboard/v1/canonical-transactions" in rules
    assert "/api/dashboard/v1/debts" in rules


def test_canonical_write_authority_fails_closed_without_dsn_even_with_services(monkeypatch):
    monkeypatch.setenv("CANONICAL_FINANCE_WRITES_ENABLED", "true")
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    try:
        register_dashboard(
            Flask(__name__),
            repository=object(),
            canonical_transaction_service=object(),
            canonical_debt_service=object(),
        )
    except RuntimeError as error:
        assert "authority requires a database DSN" in str(error)
    else:
        raise AssertionError("canonical write authority without DSN must fail closed")


def test_canonical_write_authority_refuses_injected_legacy_transaction_service(monkeypatch):
    from services import financial_schema

    monkeypatch.setenv("CANONICAL_FINANCE_WRITES_ENABLED", "true")
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://isolated-test")
    monkeypatch.setattr(
        financial_schema,
        "verify_financial_schema",
        lambda _dsn: {"ready": True},
    )

    try:
        register_dashboard(
            Flask(__name__),
            repository=object(),
            transaction_service=object(),
            canonical_transaction_service=object(),
            canonical_debt_service=object(),
        )
    except RuntimeError as error:
        assert "cannot use an injected legacy transaction service" in str(error)
    else:
        raise AssertionError("canonical authority must reject a legacy writer")


def test_canonical_write_authority_selects_postgres_dashboard_service(monkeypatch):
    from services import dashboard_transaction_service, finance_write_authority, financial_schema

    monkeypatch.setenv("CANONICAL_FINANCE_WRITES_ENABLED", "true")
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://isolated-test")
    verified = []
    selected = []
    monkeypatch.setattr(
        financial_schema,
        "verify_financial_schema",
        lambda dsn: verified.append(dsn) or {"ready": True},
    )
    monkeypatch.setattr(
        finance_write_authority,
        "assert_finance_authority_configuration",
        lambda dsn, *, writes_enabled: (dsn, writes_enabled),
    )
    monkeypatch.setattr(
        finance_write_authority,
        "PostgresAuthorityResolver",
        lambda dsn: ("resolver", dsn),
    )
    monkeypatch.setattr(
        dashboard_transaction_service,
        "PostgresDashboardTransactionService",
        lambda **kwargs: selected.append(kwargs) or object(),
    )

    app = Flask(__name__)
    register_dashboard(
        app,
        repository=object(),
        canonical_transaction_service=object(),
        canonical_debt_service=object(),
    )

    assert verified == ["postgresql://isolated-test"]
    assert len(selected) == 1
    assert app.config["CANONICAL_FINANCE_WRITES_ENABLED"] is True
