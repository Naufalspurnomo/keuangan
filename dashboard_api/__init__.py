"""Private, read-only Hollawall dashboard integration."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, Optional

from flask import Flask

from dashboard_api.repository import DashboardRepository
from dashboard_api.routes import create_dashboard_blueprint


# SHA-256 verifier for the owner VPS reverse proxy. The 384-bit bearer token
# remains owner-scoped outside Git and can be rotated through the environment.
DEFAULT_DASHBOARD_PROXY_TOKEN_HASH = "4e27151b079d42b5347a988f0a4c24280bd38af3ff23f971a47e4e6a890cc26c"


def register_dashboard(app: Flask, *, repository: Optional[Any] = None) -> None:
    """Register dashboard routes without modifying existing webhook behavior."""

    app.config.setdefault("DASHBOARD_OWNER_EMAIL", os.getenv("DASHBOARD_OWNER_EMAIL", ""))
    app.config.setdefault(
        "DASHBOARD_OWNER_PASSWORD_HASH",
        os.getenv("DASHBOARD_OWNER_PASSWORD_HASH", ""),
    )
    app.config.setdefault(
        "DASHBOARD_PROXY_TOKEN_HASH",
        os.getenv("DASHBOARD_PROXY_TOKEN_HASH", DEFAULT_DASHBOARD_PROXY_TOKEN_HASH),
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_NAME"] = "hollawall_owner_session"

    selected_repository = repository
    if selected_repository is None:
        dsn = str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
        if not dsn:
            # Registration stays explicit and safe in production. Tests and local
            # tooling can inject a repository without a database.
            return
        selected_repository = DashboardRepository(dsn)
    app.register_blueprint(create_dashboard_blueprint(selected_repository))


__all__ = ["register_dashboard"]
