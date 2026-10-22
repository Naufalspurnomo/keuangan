import hashlib
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

PROXY_TOKEN = "proxy-test-token"
PROXY_TOKEN_HASH = hashlib.sha256(PROXY_TOKEN.encode("utf-8")).hexdigest()

from flask import Flask
from werkzeug.security import generate_password_hash

from dashboard_api import register_dashboard
from dashboard_api.repository import Page


class FakeRepository:
    def __init__(self):
        self.rows = [
            {
                "id": 1,
                "source_key": "income:1",
                "transaction_date": date(2026, 10, 20),
                "amount": 10_000_000,
                "transaction_type": "Pemasukan",
                "company": "HOLLA",
                "wallet": "CV HB(101)",
                "project": "Alpha",
                "category": "Pendapatan",
                "description": "Termin",
                "recorded_by": "Naufal",
                "input_source": "WhatsApp",
                "source_wallet": None,
                "source_block": "ledger",
                "is_valid": True,
                "updated_at": datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
            },
            {
                "id": 2,
                "source_key": "expense:1",
                "transaction_date": date(2026, 10, 20),
                "amount": 2_500_000,
                "transaction_type": "Pengeluaran",
                "company": "HOLLA",
                "wallet": "CV HB(101)",
                "project": "Alpha",
                "category": "Produksi",
                "description": "Bahan",
                "recorded_by": "Naufal",
                "input_source": "WhatsApp",
                "source_wallet": None,
                "source_block": "ledger",
                "is_valid": True,
                "updated_at": datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
            },
        ]

    def fetch_filter_options(self):
        return {
            "wallets": ["CV HB(101)", "TX SBY(216)", "TX BALI(087)"],
            "companies": ["HOLLA", "HOJJA", "TEXTURIN-Surabaya", "TEXTURIN-Bali"],
            "projects": ["Alpha"],
        }

    def fetch_freshness(self):
        return {
            "last_updated_at": "2026-10-21T10:00:00+00:00",
            "row_count": 2,
            "invalid_count": 0,
        }

    def fetch_metric_rows(self, filters):
        return list(self.rows)

    def fetch_transactions(self, filters, *, limit=50, cursor=None, include_invalid=False):
        return Page(items=list(self.rows), next_cursor=None)


class DashboardRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            DASHBOARD_OWNER_EMAIL="naufalspurnomo@gmail.com",
            DASHBOARD_OWNER_PASSWORD_HASH=generate_password_hash("boss-test-password"),
            DASHBOARD_PROXY_TOKEN_HASH=PROXY_TOKEN_HASH,
        )
        register_dashboard(app, repository=FakeRepository())
        self.app = app
        self.client = app.test_client()

    def login_session(self, role="owner"):
        with self.client.session_transaction() as session:
            session["dashboard_user"] = "naufalspurnomo@gmail.com"
            session["dashboard_role"] = role

    def test_unauthenticated_requests_fail_closed(self):
        response = self.client.get("/api/dashboard/v1/overview")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "authentication_required")

    def test_snapshot_route_returns_frontend_contract_via_proxy_token(self):
        snapshot = {
            "version": "dashboard.snapshot.v1",
            "meta": {"as_of": "2026-10-21T00:00:00+00:00", "freshness": "fresh"},
            "overview": {"metrics": {"cash_balance": 123}},
            "wallets": [],
            "transactions": [],
            "debts": [],
            "cash_trend": [],
            "project_summaries": [],
        }
        with patch("dashboard_api.live_source.load_live_snapshot", return_value=snapshot):
            response = self.client.get(
                "/api/dashboard/v1/snapshot",
                headers={"X-Hollawall-Proxy-Token": PROXY_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), snapshot)
        self.assertIn("private", response.headers["Cache-Control"])

    def test_snapshot_source_failure_is_sanitized(self):
        with patch("dashboard_api.live_source.load_live_snapshot", side_effect=RuntimeError("credential leaked here")):
            response = self.client.get(
                "/api/dashboard/v1/snapshot",
                headers={"X-Hollawall-Proxy-Token": PROXY_TOKEN},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "source_unavailable")
        self.assertNotIn("credential leaked", response.get_data(as_text=True))

    def test_valid_reverse_proxy_token_allows_read_only_access(self):
        response = self.client.get(
            "/api/dashboard/v1/overview",
            headers={"X-Hollawall-Proxy-Token": PROXY_TOKEN},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["api_version"], "dashboard.v1")

    def test_reverse_proxy_token_exposes_owner_identity(self):
        response = self.client.get(
            "/api/dashboard/v1/auth/me",
            headers={"X-Hollawall-Proxy-Token": PROXY_TOKEN},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"], {"email": "naufalspurnomo@gmail.com", "role": "owner"})

    def test_invalid_reverse_proxy_token_fails_closed(self):
        response = self.client.get(
            "/api/dashboard/v1/overview",
            headers={"X-Hollawall-Proxy-Token": "wrong-token"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "authentication_required")

    def test_bearer_authorization_is_not_accepted_as_proxy_auth(self):
        response = self.client.get(
            "/api/dashboard/v1/overview",
            headers={"Authorization": f"Bearer {PROXY_TOKEN}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_malformed_reverse_proxy_hash_fails_closed(self):
        self.app.config["DASHBOARD_PROXY_TOKEN_HASH"] = "not-a-sha256"
        response = self.client.get(
            "/api/dashboard/v1/overview",
            headers={"X-Hollawall-Proxy-Token": PROXY_TOKEN},
        )

        self.assertEqual(response.status_code, 401)

    def test_non_owner_role_is_forbidden(self):
        self.login_session("viewer")

        response = self.client.get("/api/dashboard/v1/overview")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "owner_role_required")

    def test_owner_login_sets_session_and_identity_is_readable(self):
        response = self.client.post(
            "/api/dashboard/v1/auth/login",
            json={"email": "naufalspurnomo@gmail.com", "password": "boss-test-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", response.headers["Set-Cookie"])
        me = self.client.get("/api/dashboard/v1/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["data"]["email"], "naufalspurnomo@gmail.com")

    def test_bad_login_is_generic(self):
        response = self.client.post(
            "/api/dashboard/v1/auth/login",
            json={"email": "naufalspurnomo@gmail.com", "password": "wrong"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("hash", response.get_data(as_text=True).lower())
        self.assertNotIn("sql", response.get_data(as_text=True).lower())

    def test_all_launch_routes_return_versioned_envelope_and_etag(self):
        self.login_session()
        routes = (
            "overview",
            "cashflow",
            "wallets",
            "transactions",
            "projects",
            "internal-debts",
            "reports",
            "options",
        )
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(f"/api/dashboard/v1/{route}")
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload["api_version"], "dashboard.v1")
                self.assertIn("data", payload)
                self.assertIn("meta", payload)
                self.assertIn("as_of", payload["meta"])
                self.assertIn("freshness", payload["meta"])
                self.assertIn("data_completeness", payload["meta"])
                self.assertTrue(response.headers.get("ETag"))

    def test_unsupported_filter_returns_sanitized_400(self):
        self.login_session()

        response = self.client.get("/api/dashboard/v1/overview?sql=drop+table")

        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body["error"]["code"], "invalid_filter")
        self.assertNotIn("traceback", response.get_data(as_text=True).lower())

    def test_finance_routes_are_get_only(self):
        self.login_session()
        for path in ("overview", "snapshot"):
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(path=path, method=method):
                    response = getattr(self.client, method)(f"/api/dashboard/v1/{path}")
                    self.assertEqual(response.status_code, 405)

    def test_conditional_request_returns_304(self):
        self.login_session()
        first = self.client.get("/api/dashboard/v1/overview")

        second = self.client.get(
            "/api/dashboard/v1/overview",
            headers={"If-None-Match": first.headers["ETag"]},
        )

        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.get_data(), b"")


if __name__ == "__main__":
    unittest.main()
