from __future__ import annotations

import hashlib
import hmac
import json
import time

from flask import Flask

from dashboard_api.auth import (
    actor_identity,
    build_upstream_actor_assertion,
    verify_upstream_actor_assertion,
)


SECRET = "actor-assertion-test-secret-at-least-32-bytes"
BODY = b'{"amount":100000}'


def make_app(**config):
    app = Flask(__name__)
    values = {
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "DASHBOARD_ACTOR_ASSERTION_SECRET": SECRET,
        "DASHBOARD_ACTOR_ASSERTION_AUDIENCE": "hollawall-finance-api",
        "DASHBOARD_ACTOR_ASSERTION_TTL_SECONDS": 60,
        "DASHBOARD_ACTOR_ASSERTION_REQUIRED": True,
    }
    values.update(config)
    app.config.update(values)
    return app


def assertion(**changes):
    claims = {
        "actor_id": "admin-17",
        "email": "admin@example.com",
        "role": "admin",
        "aud": "hollawall-finance-api",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "method": "POST",
        "path": "/api/dashboard/v1/canonical-transactions",
        "body_sha256": hashlib.sha256(BODY).hexdigest(),
        "nonce": "nonce-unique-0000001",
    }
    claims.update(changes)
    return build_upstream_actor_assertion(claims, SECRET)


def test_signed_actor_assertion_binds_actor_role_method_path_and_body():
    app = make_app()
    token = assertion()

    with app.test_request_context(
        "/api/dashboard/v1/canonical-transactions",
        method="POST",
        data=BODY,
        headers={"X-Hollawall-Actor-Assertion": token},
    ):
        identity = verify_upstream_actor_assertion()
        assert identity == {
            "id": "admin-17",
            "email": "admin@example.com",
            "role": "admin",
            "channel": "dashboard-proxy",
        }
        assert actor_identity() == identity


def test_missing_secret_or_assertion_fails_closed_without_default():
    app = make_app(DASHBOARD_ACTOR_ASSERTION_SECRET="")
    with app.test_request_context(
        "/api/dashboard/v1/canonical-transactions", method="POST", data=BODY
    ):
        assert verify_upstream_actor_assertion() is None
        assert actor_identity() is None


def test_expired_wrong_audience_wrong_method_wrong_path_and_wrong_body_fail_closed():
    app = make_app()
    cases = (
        assertion(exp=int(time.time()) - 1),
        assertion(aud="another-api"),
        assertion(method="GET"),
        assertion(path="/api/dashboard/v1/debts"),
        assertion(body_sha256="0" * 64),
    )

    for token in cases:
        with app.test_request_context(
            "/api/dashboard/v1/canonical-transactions",
            method="POST",
            data=BODY,
            headers={"X-Hollawall-Actor-Assertion": token},
        ):
            assert verify_upstream_actor_assertion() is None


def test_tampered_or_malformed_assertion_fails_closed():
    app = make_app()
    valid = assertion()
    cases = (
        valid[:-1] + ("A" if valid[-1] != "A" else "B"),
        "not-an-assertion",
        "eyJub25jZSI6ICJ4In0.invalid",
    )
    for token in cases:
        with app.test_request_context(
            "/api/dashboard/v1/canonical-transactions",
            method="POST",
            data=BODY,
            headers={"X-Hollawall-Actor-Assertion": token},
        ):
            assert verify_upstream_actor_assertion() is None


def test_admin_and_boss_remain_distinct_principals():
    app = make_app()
    boss = assertion(actor_id="boss-1", email="boss@example.com", role="boss", nonce="boss-nonce-0000001")
    admin = assertion()

    identities = []
    for token in (boss, admin):
        with app.test_request_context(
            "/api/dashboard/v1/canonical-transactions",
            method="POST",
            data=BODY,
            headers={"X-Hollawall-Actor-Assertion": token},
        ):
            identities.append(verify_upstream_actor_assertion())

    assert identities[0]["id"] == "boss-1"
    assert identities[0]["role"] == "boss"
    assert identities[1]["id"] == "admin-17"
    assert identities[1]["role"] == "admin"


def test_compiled_proxy_secret_default_is_absent():
    from dashboard_api import register_dashboard

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test", DASHBOARD_PROXY_TOKEN_HASH="")
    register_dashboard(app, repository=object())
    assert app.config["DASHBOARD_PROXY_TOKEN_HASH"] == ""
