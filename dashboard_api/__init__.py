"""Private, read-only Hollawall dashboard integration."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, Optional

from flask import Flask

from config.wallets import normalize_wallet_company_pair
from dashboard_api.repository import DashboardRepository


def register_dashboard(
    app: Flask,
    *,
    repository: Optional[Any] = None,
    project_document_repository: Optional[Any] = None,
    transaction_service: Optional[Any] = None,
    canonical_transaction_service: Optional[Any] = None,
    canonical_debt_service: Optional[Any] = None,
) -> None:
    """Register dashboard routes without modifying existing webhook behavior."""
    # Import lazily so standalone transaction services can import contracts.
    from dashboard_api.routes import create_dashboard_blueprint
    from services.dashboard_transaction_service import GoogleSheetsTransactionAdapter
    from services.project_document_pdf import render_project_document_artifact
    from services.project_document_repository import (
        ProjectDocumentRepository,
        ProjectDocumentUnavailable,
    )

    app.config.setdefault("DASHBOARD_OWNER_EMAIL", os.getenv("DASHBOARD_OWNER_EMAIL", ""))
    app.config.setdefault(
        "DASHBOARD_OWNER_PASSWORD_HASH",
        os.getenv("DASHBOARD_OWNER_PASSWORD_HASH", ""),
    )
    app.config.setdefault(
        "DASHBOARD_PROXY_TOKEN_HASH",
        os.getenv("DASHBOARD_PROXY_TOKEN_HASH", ""),
    )
    app.config.setdefault(
        "DASHBOARD_ACTOR_ASSERTION_SECRET",
        os.getenv("DASHBOARD_ACTOR_ASSERTION_SECRET", ""),
    )
    app.config.setdefault(
        "DASHBOARD_ACTOR_ASSERTION_AUDIENCE",
        os.getenv("DASHBOARD_ACTOR_ASSERTION_AUDIENCE", "hollawall-finance-api"),
    )
    app.config.setdefault("DASHBOARD_ACTOR_ASSERTION_TTL_SECONDS", 60)
    app.config.setdefault(
        "DASHBOARD_ACTOR_ASSERTION_REQUIRED",
        str(os.getenv("DASHBOARD_ACTOR_ASSERTION_REQUIRED") or "").strip().casefold()
        in {"1", "true", "yes", "on"},
    )
    app.config.setdefault(
        "DASHBOARD_TRANSACTION_WRITES_ENABLED",
        str(os.getenv("DASHBOARD_TRANSACTION_WRITES_ENABLED") or "").strip().casefold()
        in {"1", "true", "yes", "on"},
    )
    app.config.setdefault(
        "PROJECT_DOCUMENT_WRITES_ENABLED",
        str(os.getenv("PROJECT_DOCUMENT_WRITES_ENABLED") or "").strip().casefold()
        in {"1", "true", "yes", "on"},
    )
    app.config.setdefault(
        "CANONICAL_FINANCE_API_ENABLED",
        str(os.getenv("CANONICAL_FINANCE_API_ENABLED") or "").strip().casefold()
        in {"1", "true", "yes", "on"},
    )
    # Health must only advertise project/document reads when this process has
    # actually registered the authoritative repository-backed routes.
    app.config.setdefault("PROJECT_DOCUMENT_READS_ENABLED", False)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_NAME"] = "hollawall_owner_session"

    dsn = str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    selected_repository = repository
    if selected_repository is None:
        if not dsn:
            # Registration stays explicit and safe in production. Tests and local
            # tooling can inject a repository without a database.
            return
        selected_repository = DashboardRepository(dsn)

    selected_project_documents = project_document_repository
    if selected_project_documents is None and dsn:
        selected_project_documents = ProjectDocumentRepository(
            dsn,
            renderer=render_project_document_artifact,
            receipt_authority_reader=GoogleSheetsTransactionAdapter.read_receipt_authority,
        )

    def project_uuid_exists(project_id: str, wallet: str, company: str) -> bool:
        if selected_project_documents is None:
            raise ProjectDocumentUnavailable(
                "authoritative project repository is not configured"
            )
        project = selected_project_documents.get_project(project_id)
        binding = normalize_wallet_company_pair(
            project.get("wallet", "") if isinstance(project, dict) else "",
            project.get("company", "") if isinstance(project, dict) else "",
        )
        return (
            isinstance(project, dict)
            and project.get("status") == "active"
            and binding == (wallet, company)
        )

    def project_uuid_name(project_id: str) -> str | None:
        if selected_project_documents is None:
            raise ProjectDocumentUnavailable(
                "authoritative project repository is not configured"
            )
        project = selected_project_documents.get_project(project_id)
        name = project.get("name") if isinstance(project, dict) else None
        return str(name).strip() if name else None

    app.register_blueprint(
        create_dashboard_blueprint(
            selected_repository,
            project_uuid_exists=project_uuid_exists,
            project_uuid_name=project_uuid_name,
            transaction_service=transaction_service,
        )
    )
    from dashboard_api.inbox_review import create_inbox_review_blueprint

    app.register_blueprint(create_inbox_review_blueprint())
    if selected_project_documents is not None:
        from dashboard_api.project_document_routes import (
            create_project_document_blueprint,
        )

        # Register after the legacy dashboard blueprint. Flask still selects the
        # more-specific project/document rules over the legacy /<view> route.
        app.register_blueprint(
            create_project_document_blueprint(selected_project_documents)
        )
        app.config["PROJECT_DOCUMENT_READS_ENABLED"] = True

    if app.config["CANONICAL_FINANCE_API_ENABLED"]:
        # Never expose canonical mutation routes with an in-memory fallback.
        if canonical_transaction_service is None or canonical_debt_service is None:
            if not dsn:
                raise RuntimeError("canonical finance API requires a database DSN")
            from services.canonical_finance import CanonicalFinanceService
            from services.financial_debt_repository import (
                PostgresInterwalletDebtRepository,
            )
            from services.financial_schema import verify_financial_schema
            from services.financial_transaction_repository import (
                PostgresFinancialTransactionRepository,
            )
            from services.interwallet_debt_service import InterwalletDebtService

            verify_financial_schema(dsn)
            canonical_transaction_service = canonical_transaction_service or CanonicalFinanceService(
                PostgresFinancialTransactionRepository(dsn)
            )
            canonical_debt_service = canonical_debt_service or InterwalletDebtService(
                PostgresInterwalletDebtRepository(dsn)
            )

        from dashboard_api.canonical_finance_routes import (
            create_canonical_finance_blueprint,
        )
        from dashboard_api.debt_routes import create_debt_blueprint

        app.register_blueprint(
            create_canonical_finance_blueprint(canonical_transaction_service)
        )
        app.register_blueprint(create_debt_blueprint(canonical_debt_service))


__all__ = ["register_dashboard"]
