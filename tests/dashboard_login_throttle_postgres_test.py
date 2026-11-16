from __future__ import annotations

import os

import pytest
from flask import Flask

from dashboard_api.auth import login_retry_after, record_login_result
from services.financial_schema import apply_financial_migrations, load_production_bootstrap_migrations


DSN = os.getenv("FINANCIAL_EXPORT_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="FINANCIAL_EXPORT_TEST_DATABASE_URL is not configured",
)


def _connection():
    import psycopg

    return psycopg.connect(DSN)


def _app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        DASHBOARD_LOGIN_THROTTLE_DATABASE_URL=DSN,
        DASHBOARD_LOGIN_RATE_MAX=3,
        DASHBOARD_LOGIN_RATE_BLOCK_SECONDS=60,
    )
    return app


def test_login_throttle_survives_app_restart_and_is_shared() -> None:
    apply_financial_migrations(
        DSN,
        migrations=load_production_bootstrap_migrations(),
    )
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM dashboard_login_throttle")

    email = "owner@example.com"
    source = "192.0.2.50"
    with _app().app_context():
        assert record_login_result(email, source, success=False, now=1000) == 0
        assert record_login_result(email, source, success=False, now=1001) == 0

    # A different Flask process/app observes and advances the same PostgreSQL rows.
    with _app().app_context():
        assert record_login_result(email, source, success=False, now=1002) == 60
        assert login_retry_after(email, source, now=1012) == 50

    # Successful authentication clears both account+source and source-only keys.
    with _app().app_context():
        assert record_login_result(email, source, success=True, now=1013) == 0
        assert login_retry_after(email, source, now=1013) == 0
