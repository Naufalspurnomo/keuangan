import hashlib
import unittest

from flask import Flask

from dashboard_api import register_dashboard
from dashboard_api.write_contracts import TransactionValidationError
from services.dashboard_transaction_service import (
    DashboardTransactionConflict,
    DashboardTransactionUnavailable,
)
from services.dashboard_write_requests import (
    DashboardWriteRequestConflict,
    DashboardWriteRequestUnavailable,
)


PROXY_TOKEN = "proxy-test-token"
PROXY_TOKEN_HASH = hashlib.sha256(PROXY_TOKEN.encode("utf-8")).hexdigest()
IDEMPOTENCY_KEY = "dashboard-route-test-0001"
CSRF_TOKEN = "csrf-route-test-token"


class FakeRepository:
    def fetch_filter_options(self):
        return {"projects": ["Alpha"]}


class FakeTransactionService:
    def __init__(self, *, result=None, error=None):
        self.result = result or {
            "recorded": True,
            "transaction_id": "sheet:CV HB(101):pengeluaran:7",
        }
        self.error = error
        self.calls = []

    def record(self, payload, *, actor, message_id):
        self.calls.append((payload, actor, message_id))
        if self.error:
            raise self.error
        return dict(self.result)


class DashboardTransactionRouteTests(unittest.TestCase):
    def make_app(self, service, *, enabled=True):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            DASHBOARD_OWNER_EMAIL="naufalspurnomo@gmail.com",
            DASHBOARD_PROXY_TOKEN_HASH=PROXY_TOKEN_HASH,
            DASHBOARD_TRANSACTION_WRITES_ENABLED=enabled,
        )
        register_dashboard(
            app,
            repository=FakeRepository(),
            transaction_service=service,
        )
        return app

    @staticmethod
    def payload():
        return {
            "idempotency_key": IDEMPOTENCY_KEY,
            "date": "2026-11-02",
            "scope": "project",
            "direction": "Pengeluaran",
            "amount": 125000,
            "description": "Bahan proyek",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
            "category": "Produksi",
            "project": "Alpha",
        }

    def session_login(self, client, *, role="owner", csrf=CSRF_TOKEN):
        with client.session_transaction() as session:
            session["dashboard_user"] = "naufalspurnomo@gmail.com"
            session["dashboard_role"] = role
            session["dashboard_csrf_token"] = csrf

    @staticmethod
    def headers(**extra):
        values = {
            "Content-Type": "application/json",
            "Idempotency-Key": IDEMPOTENCY_KEY,
        }
        values.update(extra)
        return values

    def test_feature_is_disabled_by_default_and_response_is_not_cacheable(self):
        service = FakeTransactionService()
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            DASHBOARD_OWNER_EMAIL="naufalspurnomo@gmail.com",
            DASHBOARD_PROXY_TOKEN_HASH=PROXY_TOKEN_HASH,
        )
        register_dashboard(app, repository=FakeRepository(), transaction_service=service)
        response = app.test_client().post(
            "/api/dashboard/v1/transactions",
            json=self.payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY, "X-Hollawall-Proxy-Token": PROXY_TOKEN},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "transaction_writes_disabled")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(service.calls, [])

    def test_owner_auth_is_required_even_when_enabled(self):
        service = FakeTransactionService()
        response = self.make_app(service).test_client().post(
            "/api/dashboard/v1/transactions",
            json=self.payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "authentication_required")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(service.calls, [])

    def test_direct_session_requires_matching_csrf_header(self):
        service = FakeTransactionService()
        client = self.make_app(service).test_client()
        self.session_login(client)
        for csrf in (None, "wrong-token"):
            headers = self.headers()
            if csrf is not None:
                headers["X-CSRF-Token"] = csrf
            with self.subTest(csrf=csrf):
                response = client.post(
                    "/api/dashboard/v1/transactions",
                    json=self.payload(),
                    headers=headers,
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["error"]["code"], "csrf_validation_failed")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(service.calls, [])

    def test_valid_direct_session_records_bound_json_request(self):
        service = FakeTransactionService()
        client = self.make_app(service).test_client()
        self.session_login(client)
        response = client.post(
            "/api/dashboard/v1/transactions",
            json=self.payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY, "X-CSRF-Token": CSRF_TOKEN},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["data"], service.result)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        payload, actor, message_id = service.calls[0]
        self.assertEqual(payload, self.payload())
        self.assertEqual(actor, {"email": "naufalspurnomo@gmail.com", "role": "owner"})
        self.assertEqual(
            message_id,
            "dashboard-api:" + hashlib.sha256(IDEMPOTENCY_KEY.encode("utf-8")).hexdigest(),
        )

    def test_proxy_owner_token_is_accepted_without_browser_csrf(self):
        service = FakeTransactionService()
        response = self.make_app(service).test_client().post(
            "/api/dashboard/v1/transactions",
            json=self.payload(),
            headers={
                "Idempotency-Key": IDEMPOTENCY_KEY,
                "X-Hollawall-Proxy-Token": PROXY_TOKEN,
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(service.calls), 1)

    def test_json_content_type_object_and_idempotency_header_are_strict(self):
        cases = (
            ({"data": "{}", "content_type": "text/plain", "headers": {"Idempotency-Key": IDEMPOTENCY_KEY}}, "json_required"),
            ({"data": "{", "content_type": "application/json", "headers": {"Idempotency-Key": IDEMPOTENCY_KEY}}, "invalid_json"),
            ({"json": [1, 2], "headers": {"Idempotency-Key": IDEMPOTENCY_KEY}}, "json_object_required"),
            ({"json": self.payload()}, "idempotency_key_required"),
            ({"json": self.payload(), "headers": {"Idempotency-Key": "different-route-key-0002"}}, "idempotency_key_mismatch"),
        )
        for request_kwargs, code in cases:
            service = FakeTransactionService()
            client = self.make_app(service).test_client()
            request_kwargs.setdefault("headers", {})["X-Hollawall-Proxy-Token"] = PROXY_TOKEN
            with self.subTest(code=code):
                response = client.post("/api/dashboard/v1/transactions", **request_kwargs)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.get_json()["error"]["code"], code)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(service.calls, [])

    def test_contract_conflicts_and_unavailability_are_sanitized(self):
        cases = (
            (TransactionValidationError("description: secret validator detail"), 422, "invalid_transaction"),
            (DashboardWriteRequestConflict("raw request hash"), 409, "transaction_conflict"),
            (DashboardTransactionConflict("raw Sheet mismatch"), 409, "transaction_conflict"),
            (DashboardWriteRequestUnavailable("raw database dsn"), 503, "transaction_unavailable"),
            (DashboardTransactionUnavailable("raw Sheets credential"), 503, "transaction_unavailable"),
            (RuntimeError("unexpected production secret"), 503, "transaction_unavailable"),
        )
        for error, status, code in cases:
            service = FakeTransactionService(error=error)
            response = self.make_app(service).test_client().post(
                "/api/dashboard/v1/transactions",
                json=self.payload(),
                headers={
                    "Idempotency-Key": IDEMPOTENCY_KEY,
                    "X-Hollawall-Proxy-Token": PROXY_TOKEN,
                },
            )
            with self.subTest(error=type(error).__name__):
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_json()["error"]["code"], code)
                self.assertNotIn(str(error), response.get_data(as_text=True))
                self.assertEqual(response.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
