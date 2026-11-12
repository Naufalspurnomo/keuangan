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
    from services.finance_write_authority import canonical_finance_writes_enabled

    app.config.setdefault(
        "CANONICAL_FINANCE_WRITES_ENABLED",
        canonical_finance_writes_enabled(),
    )
    app.config.setdefault(
        "CANONICAL_FINANCE_READS_ENABLED",
        bool(app.config["CANONICAL_FINANCE_WRITES_ENABLED"])
        or str(os.getenv("CANONICAL_FINANCE_READS_ENABLED") or "").strip().casefold()
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

    writes_enabled = bool(app.config["CANONICAL_FINANCE_WRITES_ENABLED"])
    latch_enforced = str(
        os.getenv("CANONICAL_FINANCE_LATCH_ENFORCED") or ""
    ).strip().casefold() in {"1", "true", "yes", "on"}
    canonical_runtime_required = bool(
        writes_enabled
        or app.config["CANONICAL_FINANCE_API_ENABLED"]
        or app.config["CANONICAL_FINANCE_READS_ENABLED"]
    )
    if canonical_runtime_required:
        missing_service = (
            canonical_transaction_service is None or canonical_debt_service is None
        )
        if writes_enabled and not dsn:
            raise RuntimeError("canonical finance authority requires a database DSN")
        if writes_enabled and transaction_service is not None:
            raise RuntimeError(
                "canonical finance authority cannot use an injected legacy transaction service"
            )
        if missing_service:
            if not dsn:
                raise RuntimeError("canonical finance runtime requires a database DSN")
            from services.canonical_finance import CanonicalFinanceService
            from services.financial_debt_repository import (
                PostgresInterwalletDebtRepository,
            )
            from services.financial_transaction_repository import (
                PostgresFinancialTransactionRepository,
            )
            from services.interwallet_debt_service import InterwalletDebtService

            canonical_transaction_service = canonical_transaction_service or CanonicalFinanceService(
                PostgresFinancialTransactionRepository(dsn)
            )
            canonical_debt_service = canonical_debt_service or InterwalletDebtService(
                PostgresInterwalletDebtRepository(dsn)
            )
        if writes_enabled or missing_service:
            from services.financial_schema import verify_financial_schema

            verify_financial_schema(dsn)
        assert canonical_transaction_service is not None
        assert canonical_debt_service is not None
        if writes_enabled:
            from services.finance_write_authority import (
                FinanceWriteAuthorityGateway,
                PostgresAuthorityResolver,
            )
            from services.dashboard_transaction_service import (
                PostgresDashboardTransactionService,
            )

            gateway = FinanceWriteAuthorityGateway(
                enabled=True,
                resolver=PostgresAuthorityResolver(dsn),
                finance_service=canonical_transaction_service,
                debt_service=canonical_debt_service,
            )
            app.extensions["finance_write_authority_gateway"] = gateway
            transaction_service = PostgresDashboardTransactionService(
                gateway=gateway,
                project_exists=lambda _project, _wallet, _company: False,
                project_uuid_exists=project_uuid_exists,
            )

    if writes_enabled or latch_enforced:
        if not dsn:
            raise RuntimeError("finance authority latch requires a database DSN")
        if not canonical_runtime_required:
            from services.financial_schema import verify_financial_schema

            verify_financial_schema(dsn)
        from services.finance_write_authority import (
            assert_finance_authority_configuration,
        )

        assert_finance_authority_configuration(
            dsn,
            writes_enabled=writes_enabled,
        )

    if canonical_runtime_required and dsn:
        from services.finance_write_authority import read_finance_authority

        app.extensions["canonical_finance_write_authority"] = (
            lambda selected_dsn=dsn: read_finance_authority(selected_dsn)
        )

    snapshot_loader = None
    if app.config["CANONICAL_FINANCE_READS_ENABLED"]:
        if not dsn or canonical_transaction_service is None or canonical_debt_service is None:
            raise RuntimeError("canonical finance reads require PostgreSQL services")
        if selected_project_documents is None:
            raise RuntimeError("canonical finance reads require the project repository")
        from services.canonical_dashboard_repository import CanonicalDashboardRepository
        from services.canonical_dashboard_snapshot import build_canonical_dashboard_snapshot

        dashboard_source = CanonicalDashboardRepository(dsn)

        def load_canonical_snapshot():
            effective = canonical_transaction_service.list_effective_transactions()
            return build_canonical_dashboard_snapshot(
                transaction_chains=[[record] for record in effective],
                projects=selected_project_documents.list_projects(),
                debts=canonical_debt_service.list_debts(),
                registry=dashboard_source.registry(),
            )

        snapshot_loader = load_canonical_snapshot

    app.register_blueprint(
        create_dashboard_blueprint(
            selected_repository,
            project_uuid_exists=project_uuid_exists,
            project_uuid_name=project_uuid_name,
            transaction_service=transaction_service,
            snapshot_loader=snapshot_loader,
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
        assert canonical_transaction_service is not None
        assert canonical_debt_service is not None
        from dashboard_api.canonical_finance_routes import (
            create_canonical_finance_blueprint,
        )
        from dashboard_api.debt_routes import create_debt_blueprint

        app.register_blueprint(
            create_canonical_finance_blueprint(canonical_transaction_service)
        )
        app.register_blueprint(create_debt_blueprint(canonical_debt_service))


__all__ = ["register_dashboard"]
