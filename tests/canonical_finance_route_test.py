from __future__ import annotations

import hashlib
import json
import time

from flask import Flask

from dashboard_api.auth import build_upstream_actor_assertion
from dashboard_api.canonical_finance_routes import create_canonical_finance_blueprint
from dashboard_api.debt_routes import create_debt_blueprint
from services.canonical_finance import FinanceConflict, FinanceNotFound, FinanceValidationError
from services.interwallet_debt_service import DebtConflict, DebtNotFound, DebtValidationError


SECRET = "canonical-route-test-secret-at-least-32-bytes"
AUDIENCE = "hollawall-finance-api"
TRANSACTION_ID = "00000000-0000-4000-8000-000000000501"
DEBT_ID = "00000000-0000-4000-8000-000000000601"
EVENT_ID = "00000000-0000-4000-8000-000000000701"


class FinanceProbe:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def _call(self, operation, *args, **kwargs):
        self.calls.append((operation, args, kwargs))
        if self.error:
            raise self.error
        return {"operation": operation, "duplicate": False}

    def create_transaction(self, payload, *, actor):
        return self._call("create", payload, actor=actor)

    def correct_transaction(self, transaction_id, payload, *, actor):
        return self._call("correct", transaction_id, payload, actor=actor)

    def reverse_transaction(self, transaction_id, payload, *, actor):
        return self._call("reverse", transaction_id, payload, actor=actor)

    def get_transaction(self, transaction_id):
        return self._call("get", transaction_id)

    def list_effective_transactions(self):
        return [self._call("list")]


class DebtProbe:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def _call(self, operation, *args, **kwargs):
        self.calls.append((operation, args, kwargs))
        if self.error:
            raise self.error
        return {"debt": {"id": DEBT_ID}, "duplicate": False}

    def create_debt(self, payload, *, actor):
        return self._call("create", payload, actor=actor)

    def repay_debt(self, debt_id, payload, *, actor):
        return self._call("repay", debt_id, payload, actor=actor)

    def correct_event(self, debt_id, event_id, payload, *, actor):
        return self._call("correct", debt_id, event_id, payload, actor=actor)

    def reverse_event(self, debt_id, event_id, payload, *, actor):
        return self._call("reverse", debt_id, event_id, payload, actor=actor)

    def get_debt(self, debt_id):
        return self._call("get", debt_id)["debt"]


def make_app(finance=None, debt=None):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        DASHBOARD_ACTOR_ASSERTION_SECRET=SECRET,
        DASHBOARD_ACTOR_ASSERTION_AUDIENCE=AUDIENCE,
        DASHBOARD_ACTOR_ASSERTION_TTL_SECONDS=60,
        DASHBOARD_ACTOR_ASSERTION_REQUIRED=True,
        CANONICAL_FINANCE_WRITES_ENABLED=True,
    )
    app.extensions["canonical_finance_write_authority"] = lambda: "postgresql"
    app.register_blueprint(create_canonical_finance_blueprint(finance or FinanceProbe()))
    app.register_blueprint(create_debt_blueprint(debt or DebtProbe()))
    return app


def request_parts(path, payload, *, role="admin", actor_id="admin-1", nonce=None):
    body = json.dumps(payload, separators=(",", ":")).encode()
    now = int(time.time())
    claims = {
        "actor_id": actor_id,
        "email": f"{actor_id}@example.com",
        "role": role,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 60,
        "method": "POST",
        "path": path,
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "nonce": nonce or f"route-nonce-{time.time_ns()}",
    }
    token = build_upstream_actor_assertion(claims, SECRET)
    return body, {
        "Content-Type": "application/json",
        "Idempotency-Key": payload["idempotency_key"],
        "X-Hollawall-Actor-Assertion": token,
    }


def post(client, path, payload, **identity):
    body, headers = request_parts(path, payload, **identity)
    return client.post(path, data=body, headers=headers)


def test_canonical_transaction_create_uses_real_signed_actor_and_idempotency_header():
    service = FinanceProbe()
    client = make_app(finance=service).test_client()
    payload = {"idempotency_key": "route-transaction-0001", "amount": 100_000}

    response = post(client, "/api/dashboard/v1/canonical-transactions", payload)

    assert response.status_code == 201
    operation, args, kwargs = service.calls[0]
    assert operation == "create"
    assert args[0] == payload
    assert kwargs["actor"] == {
        "id": "admin-1",
        "email": "admin-1@example.com",
        "role": "admin",
        "channel": "dashboard-proxy",
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_missing_actor_assertion_and_idempotency_mismatch_fail_before_service():
    service = FinanceProbe()
    client = make_app(finance=service).test_client()
    payload = {"idempotency_key": "route-transaction-0002", "amount": 100_000}
    raw = json.dumps(payload).encode()

    missing = client.post(
        "/api/dashboard/v1/canonical-transactions",
        data=raw,
        headers={"Content-Type": "application/json", "Idempotency-Key": payload["idempotency_key"]},
    )
    body, headers = request_parts("/api/dashboard/v1/canonical-transactions", payload)
    headers["Idempotency-Key"] = "different-idempotency-key"
    mismatch = client.post(
        "/api/dashboard/v1/canonical-transactions", data=body, headers=headers
    )

    assert missing.status_code == 401
    assert missing.get_json()["error"]["code"] == "actor_assertion_required"
    assert mismatch.status_code == 422
    assert mismatch.get_json()["error"]["code"] == "idempotency_key_mismatch"
    assert service.calls == []


def test_correction_and_repayment_accept_admin_but_reversals_are_boss_only():
    finance = FinanceProbe()
    debt = DebtProbe()
    client = make_app(finance=finance, debt=debt).test_client()
    correction = {"idempotency_key": "route-correction-0001", "expected_version": 1}
    repayment = {"idempotency_key": "route-repayment-00001", "expected_version": 1}
    reversal = {"idempotency_key": "route-reversal-000001", "expected_version": 1}

    corrected = post(
        client,
        f"/api/dashboard/v1/canonical-transactions/{TRANSACTION_ID}/corrections",
        correction,
    )
    repaid = post(client, f"/api/dashboard/v1/debts/{DEBT_ID}/repayments", repayment)
    denied_transaction = post(
        client,
        f"/api/dashboard/v1/canonical-transactions/{TRANSACTION_ID}/reversals",
        reversal,
    )
    denied_debt = post(
        client,
        f"/api/dashboard/v1/debts/{DEBT_ID}/events/{EVENT_ID}/reversals",
        reversal,
    )

    assert corrected.status_code == 201
    assert repaid.status_code == 201
    assert denied_transaction.status_code == 403
    assert denied_debt.status_code == 403
    assert [call[0] for call in finance.calls] == ["correct"]
    assert [call[0] for call in debt.calls] == ["repay"]


def test_boss_can_reverse_transaction_and_debt_event():
    finance = FinanceProbe()
    debt = DebtProbe()
    client = make_app(finance=finance, debt=debt).test_client()
    payload = {"idempotency_key": "route-boss-reverse-01", "expected_version": 1}

    transaction = post(
        client,
        f"/api/dashboard/v1/canonical-transactions/{TRANSACTION_ID}/reversals",
        payload,
        role="boss",
        actor_id="boss-1",
    )
    debt_response = post(
        client,
        f"/api/dashboard/v1/debts/{DEBT_ID}/events/{EVENT_ID}/reversals",
        payload,
        role="boss",
        actor_id="boss-1",
    )

    assert transaction.status_code == 201
    assert debt_response.status_code == 201
    assert finance.calls[0][2]["actor"]["role"] == "boss"
    assert debt.calls[0][2]["actor"]["role"] == "boss"


def test_all_canonical_mutations_fail_closed_before_service_when_runtime_writes_disabled():
    finance = FinanceProbe()
    debt = DebtProbe()
    app = make_app(finance=finance, debt=debt)
    app.config["CANONICAL_FINANCE_WRITES_ENABLED"] = False
    app.extensions["canonical_finance_write_authority"] = lambda: "postgresql"
    client = app.test_client()
    cases = (
        ("/api/dashboard/v1/canonical-transactions", "gate-transaction-create"),
        (f"/api/dashboard/v1/canonical-transactions/{TRANSACTION_ID}/corrections", "gate-transaction-correct"),
        (f"/api/dashboard/v1/canonical-transactions/{TRANSACTION_ID}/reversals", "gate-transaction-reverse"),
        ("/api/dashboard/v1/debts", "gate-debt-create-00001"),
        (f"/api/dashboard/v1/debts/{DEBT_ID}/repayments", "gate-debt-repay-00001"),
        (f"/api/dashboard/v1/debts/{DEBT_ID}/events/{EVENT_ID}/corrections", "gate-debt-correct-0001"),
        (f"/api/dashboard/v1/debts/{DEBT_ID}/events/{EVENT_ID}/reversals", "gate-debt-reverse-0001"),
    )

    for path, key in cases:
        response = post(client, path, {"idempotency_key": key, "expected_version": 1}, role="boss")
        assert response.status_code == 503, path

    assert finance.calls == []
    assert debt.calls == []


def test_all_canonical_mutations_fail_closed_before_service_when_durable_authority_is_not_postgresql():
    finance = FinanceProbe()
    debt = DebtProbe()
    app = make_app(finance=finance, debt=debt)
    app.extensions["canonical_finance_write_authority"] = lambda: "google_sheets"
    client = app.test_client()
    cases = (
        ("/api/dashboard/v1/canonical-transactions", "latch-transaction-create"),
        (f"/api/dashboard/v1/canonical-transactions/{TRANSACTION_ID}/corrections", "latch-transaction-correct"),
        (f"/api/dashboard/v1/canonical-transactions/{TRANSACTION_ID}/reversals", "latch-transaction-reverse"),
        ("/api/dashboard/v1/debts", "latch-debt-create-00001"),
        (f"/api/dashboard/v1/debts/{DEBT_ID}/repayments", "latch-debt-repay-00001"),
        (f"/api/dashboard/v1/debts/{DEBT_ID}/events/{EVENT_ID}/corrections", "latch-debt-correct-0001"),
        (f"/api/dashboard/v1/debts/{DEBT_ID}/events/{EVENT_ID}/reversals", "latch-debt-reverse-0001"),
    )

    for path, key in cases:
        response = post(client, path, {"idempotency_key": key, "expected_version": 1}, role="boss")
        assert response.status_code == 503, path

    assert finance.calls == []
    assert debt.calls == []


def test_transaction_and_debt_reads_remain_available_when_write_gate_is_closed():
    finance = FinanceProbe()
    debt = DebtProbe()
    app = make_app(finance=finance, debt=debt)
    app.config["CANONICAL_FINANCE_WRITES_ENABLED"] = False
    app.extensions["canonical_finance_write_authority"] = lambda: "google_sheets"
    app.config["DASHBOARD_ACTOR_ASSERTION_REQUIRED"] = False
    client = app.test_client()
    with client.session_transaction() as session:
        session["dashboard_user"] = "boss@example.com"
        session["dashboard_role"] = "owner"

    listed = client.get("/api/dashboard/v1/canonical-transactions")
    detail = client.get(f"/api/dashboard/v1/canonical-transactions/{TRANSACTION_ID}")
    debt_detail = client.get(f"/api/dashboard/v1/debts/{DEBT_ID}")

    assert listed.status_code == 200
    assert detail.status_code == 200
    assert debt_detail.status_code == 200
    assert [call[0] for call in finance.calls] == ["list", "get"]
    assert [call[0] for call in debt.calls] == ["get"]


def test_domain_errors_are_sanitized_and_mapped():
    cases = (
        (FinanceValidationError("amount: secret"), 422, "invalid_finance_command"),
        (FinanceConflict("raw hash"), 409, "finance_conflict"),
        (FinanceNotFound("raw id"), 404, "finance_not_found"),
        (RuntimeError("database credential"), 503, "finance_unavailable"),
    )
    for error, status, code in cases:
        client = make_app(finance=FinanceProbe(error=error)).test_client()
        payload = {"idempotency_key": "route-errors-0000001"}
        response = post(client, "/api/dashboard/v1/canonical-transactions", payload)
        assert response.status_code == status
        assert response.get_json()["error"]["code"] == code
        assert str(error) not in response.get_data(as_text=True)

    debt_cases = (
        (DebtValidationError("amount: secret"), 422, "invalid_debt_command"),
        (DebtConflict("raw hash"), 409, "debt_conflict"),
        (DebtNotFound("raw id"), 404, "debt_not_found"),
        (RuntimeError("database credential"), 503, "debt_unavailable"),
    )
    for error, status, code in debt_cases:
        client = make_app(debt=DebtProbe(error=error)).test_client()
        payload = {"idempotency_key": "route-debt-errors-001"}
        response = post(client, "/api/dashboard/v1/debts", payload)
        assert response.status_code == status
        assert response.get_json()["error"]["code"] == code
        assert str(error) not in response.get_data(as_text=True)
