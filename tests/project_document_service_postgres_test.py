"""PostgreSQL integration for the project-document service boundary."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from services.project_document_repository import (
    ProjectDocumentConflict,
    ProjectDocumentRepository,
)
from services.project_documents import ProjectDocumentService


pytestmark = pytest.mark.skipif(
    not os.getenv("PROJECT_DOCUMENT_TEST_DATABASE_URL"),
    reason="PROJECT_DOCUMENT_TEST_DATABASE_URL is not configured",
)

ACTOR = {"email": "owner@example.com"}
FIXED_NOW = datetime(2026, 11, 3, 4, 0, tzinfo=ZoneInfo("UTC"))


def renderer(snapshot):
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return b"%PDF-1.7\n" + payload + b"\n%%EOF\n", "service-test/1"


@pytest.fixture()
def repository():
    import psycopg

    dsn = os.environ["PROJECT_DOCUMENT_TEST_DATABASE_URL"]
    migration = (
        Path(__file__).parents[1]
        / "dashboard_api/migrations/003_project_documents.sql"
    ).read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
            cursor.execute(
                """
                CREATE TABLE financial_ledger (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    source_key TEXT NOT NULL UNIQUE,
                    source_sheet TEXT NOT NULL,
                    source_row INTEGER,
                    source_block TEXT NOT NULL,
                    message_id TEXT,
                    transaction_date DATE,
                    amount BIGINT,
                    transaction_type TEXT NOT NULL,
                    company TEXT,
                    wallet TEXT,
                    project TEXT,
                    category TEXT,
                    description TEXT,
                    recorded_by TEXT,
                    input_source TEXT,
                    source_wallet TEXT,
                    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(migration)
    store = ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=renderer,
    )
    store.upsert_issuer_profile(
        issuer_key="hollawall",
        legal_name="CV Holla Berkreasi",
        display_name="Hollawall",
        number_code="HW",
        address="Surabaya",
        actor=ACTOR,
        expected_version=0,
        idempotency_key="service-issuer-create-0001",
    )
    return store


def service(repository):
    return ProjectDocumentService(repository)


def set_total(repository, document, amount, key):
    return repository.update_draft(
        document["id"],
        {
            "lines": [
                {
                    "description": "Commercial amount",
                    "quantity": "1",
                    "unit": "unit",
                    "unit_price": amount,
                }
            ]
        },
        expected_version=document["lock_version"],
        idempotency_key=key,
        actor=ACTOR,
    )


def issue(repository, document, key):
    return repository.issue_document(
        document["id"],
        expected_version=document["lock_version"],
        idempotency_key=key,
        actor=ACTOR,
    )


def test_service_prefills_final_from_authoritative_issued_sales_order_and_invoices(repository):
    subject = service(repository)
    created = subject.create_project(
        {
            "name": "Fredding Universe",
            "client_name": "Stefano",
            "issuer_key": "hollawall",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
        },
        idempotency_key="service-project-create-0001",
        actor=ACTOR,
    )
    sales_order = set_total(
        repository,
        created["sales_order"],
        12_668_400,
        "service-sales-order-update-0001",
    )
    issue(repository, sales_order, "service-sales-order-issue-0001")

    dp = subject.create_invoice(
        created["project"]["id"],
        kind="DP",
        values={
            "lines": [
                {
                    "description": "DP",
                    "quantity": "1",
                    "unit": "termin",
                    "unit_price": 5_000_000,
                }
            ]
        },
        idempotency_key="service-dp-create-0001",
        actor=ACTOR,
    )
    issue(repository, dp, "service-dp-issue-0001")

    final = subject.create_invoice(
        created["project"]["id"],
        kind="FINAL",
        values={},
        idempotency_key="service-final-create-0001",
        actor=ACTOR,
    )

    assert final["invoice_kind"] == "FINAL"
    assert final["lines"][0]["line_total"] == 7_668_400
    issued_final = issue(repository, final, "service-final-issue-0001")
    assert issued_final["immutable_snapshot"]["totals"]["total"] == 7_668_400


def test_service_final_prefill_fails_closed_without_issued_sales_order(repository):
    subject = service(repository)
    created = subject.create_project(
        {
            "name": "No Order",
            "client_name": "Client",
            "issuer_key": "hollawall",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
        },
        idempotency_key="service-project-create-0002",
        actor=ACTOR,
    )

    with pytest.raises(ProjectDocumentConflict, match="exactly one active issued Sales Order"):
        subject.create_invoice(
            created["project"]["id"],
            kind="FINAL",
            values={},
            idempotency_key="service-final-create-0002",
            actor=ACTOR,
        )


def test_repository_replays_project_and_invoice_after_midnight_and_status_change(repository):
    moments = iter(
        [
            datetime(2026, 11, 3, 16, 59, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 11, 3, 17, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 11, 3, 17, 2, tzinfo=ZoneInfo("UTC")),
        ]
    )
    repository._now = lambda: next(moments)
    project_key = "service-replay-project-0001"
    values = {
        "name": "Midnight Replay",
        "client_name": "Client",
        "issuer_key": "hollawall",
        "wallet": "CV HB(101)",
        "company": "HOLLA",
    }
    first = repository.create_project_with_sales_order(
        values, idempotency_key=project_key, actor=ACTOR
    )
    replay = repository.create_project_with_sales_order(
        values, idempotency_key=project_key, actor=ACTOR
    )
    assert replay == first
    assert replay["sales_order"]["issue_date"] == "2026-11-03"
    assert replay["sales_order"]["valid_until"] == "2026-11-17"

    invoice_values = {
        "invoice_kind": "DP",
        "tax_percent": "0",
        "lines": [
            {
                "description": "DP",
                "quantity": "1",
                "unit": "termin",
                "unit_price": 100_000,
            }
        ],
    }
    sales_order = set_total(
        repository,
        first["sales_order"],
        1_000_000,
        "service-replay-sales-order-update-0001",
    )
    issue(repository, sales_order, "service-replay-sales-order-issue-0001")
    invoice_key = "service-replay-invoice-0001"
    invoice = repository.create_invoice_draft(
        first["project"]["id"],
        values=invoice_values,
        idempotency_key=invoice_key,
        actor=ACTOR,
    )
    repository.update_project(
        first["project"]["id"],
        {"status": "completed"},
        expected_version=first["project"]["lock_version"],
        idempotency_key="service-replay-project-status-0001",
        actor=ACTOR,
    )
    assert repository.create_invoice_draft(
        first["project"]["id"],
        values=invoice_values,
        idempotency_key=invoice_key,
        actor=ACTOR,
    ) == invoice


def test_issue_replay_does_not_consume_clock_or_recheck_later_project_state(repository):
    created = repository.create_project_with_sales_order(
        {
            "name": "Issue Replay",
            "client_name": "Client",
            "issuer_key": "hollawall",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
        },
        idempotency_key="service-issue-replay-project-0001",
        actor=ACTOR,
    )
    sales_order = set_total(
        repository,
        created["sales_order"],
        100_000,
        "service-issue-replay-update-0001",
    )
    clock_calls = []

    def first_clock():
        clock_calls.append("called")
        return FIXED_NOW

    repository._now = first_clock
    key = "service-issue-replay-command-0001"
    issued = repository.issue_document(
        sales_order["id"],
        expected_version=sales_order["lock_version"],
        idempotency_key=key,
        actor=ACTOR,
    )
    repository.update_project(
        created["project"]["id"],
        {"status": "completed"},
        expected_version=created["project"]["lock_version"],
        idempotency_key="service-issue-replay-status-0001",
        actor=ACTOR,
    )

    def forbidden_clock():
        raise AssertionError("idempotent replay must not read the clock")

    repository._now = forbidden_clock
    repository._renderer = None
    replay = repository.issue_document(
        sales_order["id"],
        expected_version=sales_order["lock_version"],
        idempotency_key=key,
        actor=ACTOR,
    )
    assert replay == issued
    assert clock_calls == ["called"]


def test_repository_invoice_command_applies_dp_progress_and_final_policy(repository):
    subject = service(repository)
    created = subject.create_project(
        {
            "name": "Invoice Policy",
            "client_name": "Client",
            "issuer_key": "hollawall",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
        },
        idempotency_key="invoice-policy-project-0001",
        actor=ACTOR,
    )
    sales_order = set_total(
        repository,
        created["sales_order"],
        1_000_001,
        "invoice-policy-sales-order-update-0001",
    )
    issue(repository, sales_order, "invoice-policy-sales-order-issue-0001")

    dp = subject.create_invoice(
        created["project"]["id"],
        kind="DP",
        values={},
        idempotency_key="invoice-policy-dp-create-0001",
        actor=ACTOR,
    )
    assert dp["lines"][0]["line_total"] == 500_001

    with pytest.raises(Exception, match="PROGRESS invoice requires explicit lines"):
        subject.create_invoice(
            created["project"]["id"],
            kind="PROGRESS",
            values={},
            idempotency_key="invoice-policy-progress-create-0001",
            actor=ACTOR,
        )
    with pytest.raises(Exception, match="cannot add discount or tax"):
        subject.create_invoice(
            created["project"]["id"],
            kind="FINAL",
            values={"tax_percent": "1"},
            idempotency_key="invoice-policy-final-tax-create-0001",
            actor=ACTOR,
        )


def test_active_final_blocks_later_invoice_until_void(repository):
    subject = service(repository)
    created = subject.create_project(
        {
            "name": "Final Lifecycle",
            "client_name": "Client",
            "issuer_key": "hollawall",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
        },
        idempotency_key="final-lifecycle-project-0001",
        actor=ACTOR,
    )
    sales_order = set_total(
        repository,
        created["sales_order"],
        900_000,
        "final-lifecycle-sales-order-update-0001",
    )
    issue(repository, sales_order, "final-lifecycle-sales-order-issue-0001")
    final = subject.create_invoice(
        created["project"]["id"],
        kind="FINAL",
        values={},
        idempotency_key="final-lifecycle-final-create-0001",
        actor=ACTOR,
    )
    issued_final = issue(repository, final, "final-lifecycle-final-issue-0001")
    with pytest.raises(ProjectDocumentConflict, match="active FINAL"):
        subject.create_invoice(
            created["project"]["id"],
            kind="DP",
            values={"lines": [{
                "description": "Late DP",
                "quantity": "1",
                "unit": "termin",
                "unit_price": 1,
            }]},
            idempotency_key="final-lifecycle-late-dp-create-0001",
            actor=ACTOR,
        )
    repository.void_document(
        issued_final["id"],
        reason="Commercial correction",
        expected_version=issued_final["lock_version"],
        idempotency_key="final-lifecycle-final-void-0001",
        actor=ACTOR,
    )
    replacement = subject.create_invoice(
        created["project"]["id"],
        kind="FINAL",
        values={},
        idempotency_key="final-lifecycle-final-replacement-0001",
        actor=ACTOR,
    )
    assert replacement["lines"][0]["line_total"] == 900_000


@pytest.mark.parametrize(
    "lines",
    [
        [
            {
                "description": "Excess scale",
                "quantity": "1.00001",
                "unit": "unit",
                "unit_price": 1,
            }
        ],
        [
            {
                "description": "Overflow",
                "quantity": "2",
                "unit": "unit",
                "unit_price": 9_223_372_036_854_775_807,
            }
        ],
        [
            {
                "description": f"Line {position}",
                "quantity": "1",
                "unit": "unit",
                "unit_price": 0,
            }
            for position in range(501)
        ],
    ],
)
def test_repository_direct_document_create_enforces_numeric_boundaries(repository, lines):
    created = repository.create_project_with_sales_order(
        {
            "name": "Numeric Boundary",
            "client_name": "Client",
            "issuer_key": "hollawall",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
        },
        idempotency_key=f"service-numeric-project-{len(lines):04d}",
        actor=ACTOR,
    )
    sales_order = set_total(
        repository,
        created["sales_order"],
        1_000_000,
        f"service-numeric-sales-order-update-{len(lines):04d}",
    )
    issue(
        repository,
        sales_order,
        f"service-numeric-sales-order-issue-{len(lines):04d}",
    )
    with pytest.raises(Exception) as captured:
        repository.create_invoice_draft(
            created["project"]["id"],
            values={"invoice_kind": "DP", "lines": lines},
            idempotency_key=f"service-numeric-document-{len(lines):04d}",
            actor=ACTOR,
        )
    assert captured.type.__name__ == "DocumentCalculationError"
