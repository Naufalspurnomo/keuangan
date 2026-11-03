import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from services.project_document_repository import (
    ProjectDocumentConflict,
    ProjectDocumentRepository,
    ProjectDocumentUnavailable,
    project_document_schema_health,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("PROJECT_DOCUMENT_TEST_DATABASE_URL"),
    reason="PROJECT_DOCUMENT_TEST_DATABASE_URL is not configured",
)

ACTOR = {"email": "owner@example.com"}
FIXED_NOW = datetime(2026, 12, 31, 18, 30, tzinfo=ZoneInfo("UTC"))


def deterministic_renderer(snapshot):
    body = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return b"%PDF-1.7\n" + body + b"\n%%EOF\n", "test-renderer/1"


@pytest.fixture()
def dsn():
    selected = os.environ["PROJECT_DOCUMENT_TEST_DATABASE_URL"]
    import psycopg

    migration = (
        Path(__file__).parents[1]
        / "dashboard_api/migrations/003_project_documents.sql"
    ).read_text(encoding="utf-8")
    with psycopg.connect(selected, autocommit=True) as connection:
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
    return selected


@pytest.fixture()
def repository(dsn):
    return ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=deterministic_renderer,
    )


def issuer(repository, *, issuer_key="hollawall", number_code="HW", key=None):
    return repository.upsert_issuer_profile(
        issuer_key=issuer_key,
        legal_name="CV Holla Berkreasi",
        display_name="Hollawall",
        number_code=number_code,
        address="Surabaya",
        actor=ACTOR,
        expected_version=0,
        idempotency_key=key or f"issuer-create-{issuer_key}-0001",
    )


def project(repository, *, key="project-create-key-0001", status="planned"):
    profile = issuer(repository)
    return repository.create_project_with_sales_order(
        {
            "name": "Backdrop Launch",
            "client_name": "PT Client",
            "client_company": "PT Client",
            "client_address": "Surabaya",
            "client_contact": "+628123",
            "issuer_key": profile["issuer_key"],
            "wallet": "CV HB(101)",
            "company": "HOLLA",
            "status": status,
            "start_date": "2026-11-03",
            "contract_notes": "A5 documents",
        },
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


def receipt(repository, project_id, key):
    return repository.create_document_draft(
        project_id,
        document_type="receipt",
        values={},
        idempotency_key=key,
        actor=ACTOR,
    )


def insert_income(dsn, project_id, amount=500_000, source_key=None):
    import psycopg
    from psycopg.types.json import Jsonb

    selected = source_key or f"test:{uuid.uuid4()}"
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO financial_ledger (
                    source_key, source_sheet, source_row, source_block,
                    transaction_date, amount, transaction_type, company,
                    wallet, project, is_valid, payload
                ) VALUES (
                    %s, 'CV HB(101)', 1, 'pemasukan', DATE '2026-11-03',
                    %s, 'Pemasukan', 'HOLLA', 'CV HB(101)', %s, TRUE, %s
                )
                """,
                (selected, amount, project_id, Jsonb({"cash_authority": "sheets"})),
            )
    return selected


def test_profile_upsert_is_idempotent_versioned_audited_and_code_unique(repository, dsn):
    import psycopg

    first = issuer(repository)
    replay = issuer(repository)
    assert replay == first
    assert first["profile_version"] == 1

    with pytest.raises(ProjectDocumentConflict, match="version"):
        repository.upsert_issuer_profile(
            issuer_key="hollawall",
            legal_name="Changed",
            display_name="Hollawall",
            number_code="HW",
            address="Surabaya",
            actor=ACTOR,
            expected_version=0,
            idempotency_key="issuer-stale-update-0001",
        )

    updated = repository.upsert_issuer_profile(
        issuer_key="hollawall",
        legal_name="CV Holla Berkreasi Updated",
        display_name="Hollawall",
        number_code="HW",
        address="Surabaya",
        actor=ACTOR,
        expected_version=1,
        idempotency_key="issuer-update-key-0001",
    )
    assert updated["profile_version"] == 2

    with pytest.raises(ProjectDocumentConflict, match="number_code"):
        issuer(repository, issuer_key="other", number_code="hw")

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_type, profile_version FROM project_issuer_profile_events "
                "WHERE issuer_key = 'hollawall' ORDER BY id"
            )
            assert cursor.fetchall() == [("issuer.created", 1), ("issuer.updated", 2)]


def test_project_creation_defaults_and_invoice_status_restrictions(repository):
    created = project(repository)
    sales_order = created["sales_order"]
    assert sales_order["issue_date"] == "2027-01-01"
    assert sales_order["valid_until"] == "2027-01-15"

    invoice = repository.create_document_draft(
        created["project"]["id"],
        document_type="invoice",
        values={"invoice_kind": "DP"},
        idempotency_key="invoice-create-key-0001",
        actor=ACTOR,
    )
    assert invoice["issue_date"] == "2027-01-01"
    assert invoice["due_date"] == "2027-01-08"

    completed = repository.update_project(
        created["project"]["id"],
        {"status": "completed"},
        expected_version=created["project"]["lock_version"],
        idempotency_key="project-complete-key-0001",
        actor=ACTOR,
    )
    assert completed["status"] == "completed"
    with pytest.raises(ProjectDocumentConflict, match="planned or active"):
        repository.create_document_draft(
            completed["id"],
            document_type="invoice",
            values={"invoice_kind": "PROGRESS"},
            idempotency_key="invoice-create-key-0002",
            actor=ACTOR,
        )


def test_canonical_issuance_renders_locked_state_and_persists_exact_bytes(repository):
    created = project(repository)
    draft = repository.update_draft(
        created["sales_order"]["id"],
        {
            "document_discount_percent": "10",
            "tax_percent": "2",
            "lines": [
                {
                    "description": "Backdrop",
                    "quantity": "2.5",
                    "unit": "m2",
                    "unit_price": 100_000,
                }
            ],
        },
        expected_version=created["sales_order"]["lock_version"],
        idempotency_key="draft-update-key-0001",
        actor=ACTOR,
    )

    issued = issue(repository, draft, "document-issue-key-0001")
    snapshot = issued["immutable_snapshot"]
    assert issued["official_number"] == "SO/HW/2027/000001"
    assert snapshot["document"]["official_number"] == issued["official_number"]
    assert snapshot["document"]["id"] == draft["id"]
    assert snapshot["issuer"]["legal_name"] == "CV Holla Berkreasi"
    assert snapshot["project"]["client_name"] == "PT Client"
    assert snapshot["lines"][0]["line_total"] == 250_000
    assert snapshot["totals"] == {
        "subtotal": 250_000,
        "document_discount": 25_000,
        "taxable_base": 225_000,
        "tax_percent": "2.0000",
        "tax": 4_500,
        "total": 229_500,
    }
    assert issued["snapshot_sha256"] == hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    expected_pdf, expected_version = deterministic_renderer(snapshot)
    artifact = repository.get_artifact(draft["id"])
    assert artifact["bytes"] == expected_pdf
    assert artifact["sha256"] == hashlib.sha256(expected_pdf).hexdigest()
    assert artifact["renderer_version"] == expected_version


def test_renderer_failure_and_invalid_pdf_roll_back_number_and_issuance(dsn):
    failing = ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=lambda _snapshot: (_ for _ in ()).throw(RuntimeError("renderer failed")),
    )
    created = project(failing)
    draft = created["sales_order"]
    with pytest.raises(ProjectDocumentUnavailable, match="RuntimeError"):
        issue(failing, draft, "document-issue-failure-0001")
    assert failing.get_document(draft["id"])["status"] == "draft"

    invalid = ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=lambda _snapshot: (b"not-a-pdf", "bad/1"),
    )
    with pytest.raises(ProjectDocumentUnavailable, match="invalid PDF"):
        issue(invalid, draft, "document-issue-failure-0002")

    valid = ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=deterministic_renderer,
    )
    issued = issue(valid, draft, "document-issue-retry-0001")
    assert issued["official_number"] == "SO/HW/2027/000001"


def test_concurrent_numbering_uses_independent_connections_and_replays(repository, dsn):
    created = project(repository)
    second = repository.create_document_draft(
        created["project"]["id"],
        document_type="sales_order",
        values={},
        idempotency_key="second-sales-order-0001",
        actor=ACTOR,
    )
    barrier = threading.Barrier(2)

    def run(document, key):
        local = ProjectDocumentRepository(
            dsn, now=lambda: FIXED_NOW, renderer=deterministic_renderer
        )
        barrier.wait(timeout=5)
        return issue(local, document, key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: run(*args),
                [
                    (created["sales_order"], "concurrent-issue-key-0001"),
                    (second, "concurrent-issue-key-0002"),
                ],
            )
        )
    assert {item["official_number"] for item in results} == {
        "SO/HW/2027/000001",
        "SO/HW/2027/000002",
    }

    # Two independent transactions with one key converge on the committed response.
    third = repository.create_document_draft(
        created["project"]["id"],
        document_type="sales_order",
        values={},
        idempotency_key="third-sales-order-0001",
        actor=ACTOR,
    )
    replay_barrier = threading.Barrier(2)

    def replay_issue():
        local = ProjectDocumentRepository(
            dsn, now=lambda: FIXED_NOW, renderer=deterministic_renderer
        )
        replay_barrier.wait(timeout=5)
        return issue(local, third, "concurrent-replay-key-0001")

    with ThreadPoolExecutor(max_workers=2) as executor:
        replays = list(executor.map(lambda _index: replay_issue(), range(2)))
    assert replays[0] == replays[1]
    assert replays[0]["official_number"] == "SO/HW/2027/000003"


def test_draft_allocations_reserve_income_and_concurrent_overreservation_fails(repository, dsn):
    created = project(repository)
    project_id = created["project"]["id"]
    first = receipt(repository, project_id, "receipt-create-key-0001")
    second = receipt(repository, project_id, "receipt-create-key-0002")
    source_key = insert_income(dsn, project_id)
    barrier = threading.Barrier(2)

    def allocate(document, key):
        local = ProjectDocumentRepository(dsn, renderer=deterministic_renderer)
        barrier.wait(timeout=5)
        return local.lock_allocations(
            document["id"],
            [{"ledger_source_key": source_key, "amount": 300_000}],
            expected_version=document["lock_version"],
            idempotency_key=key,
            actor=ACTOR,
        )

    outcomes = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(allocate, first, "allocation-concurrent-key-0001"),
            executor.submit(allocate, second, "allocation-concurrent-key-0002"),
        ]
        for future in futures:
            try:
                outcomes.append(future.result())
            except ProjectDocumentConflict as exc:
                outcomes.append(exc)
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum(isinstance(item, ProjectDocumentConflict) for item in outcomes) == 1
    assert "exceeds available income" in str(
        next(item for item in outcomes if isinstance(item, ProjectDocumentConflict))
    )


def test_allocation_locks_are_deterministic_and_issue_blocks_source_mutation(repository, dsn):
    import psycopg

    created = project(repository)
    project_id = created["project"]["id"]
    draft = receipt(repository, project_id, "receipt-create-key-0010")
    source_b = insert_income(dsn, project_id, amount=200_000, source_key="source:b")
    source_a = insert_income(dsn, project_id, amount=200_000, source_key="source:a")
    allocated = repository.lock_allocations(
        draft["id"],
        [
            {"ledger_source_key": source_b, "amount": 100_000},
            {"ledger_source_key": source_a, "amount": 100_000},
        ],
        expected_version=draft["lock_version"],
        idempotency_key="allocation-order-key-0001",
        actor=ACTOR,
    )

    renderer_entered = threading.Event()
    renderer_release = threading.Event()

    def blocking_renderer(snapshot):
        renderer_entered.set()
        assert renderer_release.wait(timeout=10)
        return deterministic_renderer(snapshot)

    issuing = ProjectDocumentRepository(
        dsn, now=lambda: FIXED_NOW, renderer=blocking_renderer
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            issue, issuing, allocated, "receipt-issue-blocking-key-0001"
        )
        assert renderer_entered.wait(timeout=5)
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with psycopg.connect(dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '250ms'")
                    cursor.execute(
                        "UPDATE financial_ledger SET amount = amount + 1 WHERE source_key = %s",
                        (source_a,),
                    )
        renderer_release.set()
        issued = future.result(timeout=10)
    assert issued["status"] == "issued"
    assert [item["ledger_source_key"] for item in issued["immutable_snapshot"]["allocations"]] == [
        "source:a",
        "source:b",
    ]


def test_final_revision_supersession_is_atomic_and_void_allows_recreate(repository, dsn):
    import psycopg

    created = project(repository)
    project_id = created["project"]["id"]
    final = repository.create_document_draft(
        project_id,
        document_type="invoice",
        values={"invoice_kind": "FINAL", "lines": [{"description": "Final", "quantity": 1, "unit": "unit", "unit_price": 1}]},
        idempotency_key="final-create-key-0001",
        actor=ACTOR,
    )
    issued = issue(repository, final, "final-issue-key-0001")
    revision = repository.revise_document(
        issued["id"],
        expected_version=issued["lock_version"],
        idempotency_key="final-revise-key-0001",
        actor=ACTOR,
    )
    assert revision["status"] == "draft"
    replacement = issue(repository, revision, "final-revision-issue-key-0001")
    original = repository.get_document(issued["id"])
    assert original["status"] == "superseded"
    assert original["superseded_by_id"] == replacement["id"]

    voided = repository.void_document(
        replacement["id"],
        reason="Commercial correction",
        expected_version=replacement["lock_version"],
        idempotency_key="final-void-key-0001",
        actor=ACTOR,
    )
    recreated = repository.create_document_draft(
        project_id,
        document_type="invoice",
        values={"invoice_kind": "FINAL"},
        idempotency_key="final-recreate-key-0001",
        actor=ACTOR,
    )
    assert voided["status"] == "void"
    assert recreated["status"] == "draft"

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM project_documents WHERE project_id = %s "
                "AND document_type = 'invoice' AND invoice_kind = 'FINAL' "
                "AND (status = 'issued' OR (status = 'draft' AND revision_of_id IS NULL))",
                (project_id,),
            )
            assert cursor.fetchone()[0] == 1


def test_concurrent_final_revision_allows_only_one_pending_draft(repository, dsn):
    created = project(repository)
    final = repository.create_document_draft(
        created["project"]["id"],
        document_type="invoice",
        values={"invoice_kind": "FINAL"},
        idempotency_key="final-concurrent-create-0001",
        actor=ACTOR,
    )
    issued = issue(repository, final, "final-concurrent-issue-0001")
    barrier = threading.Barrier(2)

    def revise(key):
        local = ProjectDocumentRepository(dsn, renderer=deterministic_renderer)
        barrier.wait(timeout=5)
        return local.revise_document(
            issued["id"],
            expected_version=issued["lock_version"],
            idempotency_key=key,
            actor=ACTOR,
        )

    outcomes = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(revise, "final-concurrent-revise-0001"),
            executor.submit(revise, "final-concurrent-revise-0002"),
        ]
        for future in futures:
            try:
                outcomes.append(future.result())
            except (ProjectDocumentConflict, ProjectDocumentUnavailable) as exc:
                outcomes.append(exc)
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum(isinstance(item, Exception) for item in outcomes) == 1


def test_sql_lifecycle_terminal_immutability_and_no_delete_guards(repository, dsn):
    import psycopg

    created = project(repository)
    draft = created["sales_order"]
    with pytest.raises(psycopg.errors.RaiseException, match="invalid project document transition"):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE project_documents SET status = 'void', void_reason = 'bad', "
                    "voided_at = NOW() WHERE id = %s",
                    (draft["id"],),
                )

    draft = repository.update_draft(
        draft["id"],
        {"lines": [{"description": "Guarded", "quantity": 1, "unit": "unit", "unit_price": 1}]},
        expected_version=draft["lock_version"],
        idempotency_key="guard-draft-update-0001",
        actor=ACTOR,
    )
    issued = issue(repository, draft, "guard-issue-key-0001")
    voided = repository.void_document(
        issued["id"],
        reason="Cancelled",
        expected_version=issued["lock_version"],
        idempotency_key="guard-void-key-0001",
        actor=ACTOR,
    )
    with pytest.raises(psycopg.errors.RaiseException, match="terminal"):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE project_documents SET void_reason = 'tampered' WHERE id = %s",
                    (voided["id"],),
                )
    with pytest.raises(psycopg.errors.RaiseException, match="children are immutable"):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM project_document_lines WHERE document_id = %s",
                    (voided["id"],),
                )
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be hard deleted"):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM project_documents WHERE id = %s", (voided["id"],))
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be hard deleted"):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM projects WHERE id = %s", (created["project"]["id"],))


def test_schema_health_detects_missing_exact_trigger(repository, dsn):
    import psycopg

    assert project_document_schema_health(dsn)["ready"] is True
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER trg_projects_no_delete ON projects")
    status = project_document_schema_health(dsn)
    assert status["ready"] is False
    assert status["triggers"] is False
