import os
import uuid
from pathlib import Path

import pytest

from services.project_document_repository import ProjectDocumentConflict, ProjectDocumentRepository


pytestmark = pytest.mark.skipif(
    not os.getenv("PROJECT_DOCUMENT_TEST_DATABASE_URL"),
    reason="PROJECT_DOCUMENT_TEST_DATABASE_URL is not configured",
)


@pytest.fixture()
def repository():
    dsn = os.environ["PROJECT_DOCUMENT_TEST_DATABASE_URL"]
    import psycopg

    migration = (Path(__file__).parents[1] / "dashboard_api/migrations/003_project_documents.sql").read_text(
        encoding="utf-8"
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
            cursor.execute(
                "TRUNCATE project_document_commands, project_document_events, "
                "project_document_artifacts, project_document_allocations, project_document_lines, "
                "project_documents, project_scopes, projects, project_document_number_counters, "
                "project_issuer_profiles RESTART IDENTITY CASCADE"
            )
    return ProjectDocumentRepository(dsn)


def issuer(repository):
    return repository.upsert_issuer_profile(
        issuer_key="hollawall",
        legal_name="CV Holla Berkreasi",
        display_name="Hollawall",
        number_code="HW",
        address="Surabaya",
        actor={"email": "owner@example.com"},
    )


def test_project_creation_is_idempotent_and_atomically_gets_one_sales_order_draft(repository):
    profile = issuer(repository)
    command = {
        "name": "Backdrop Launch",
        "client_name": "PT Client",
        "client_company": "PT Client",
        "client_address": "Surabaya",
        "client_contact": "+628123",
        "issuer_key": profile["issuer_key"],
        "wallet": "CV HB(101)",
        "company": "HOLLA",
        "status": "planned",
        "start_date": "2026-11-03",
        "contract_notes": "A5 documents",
    }

    first = repository.create_project_with_sales_order(
        command,
        idempotency_key="project-create-key-0001",
        actor={"email": "owner@example.com"},
    )
    replay = repository.create_project_with_sales_order(
        command,
        idempotency_key="project-create-key-0001",
        actor={"email": "owner@example.com"},
    )

    assert replay == first
    assert first["project"]["id"]
    assert first["sales_order"]["status"] == "draft"
    assert first["sales_order"]["official_number"] is None
    documents = repository.list_documents(first["project"]["id"])
    assert len(documents) == 1
    assert documents[0]["document_type"] == "sales_order"

    with pytest.raises(ProjectDocumentConflict, match="idempotency"):
        repository.create_project_with_sales_order(
            {**command, "name": "Different"},
            idempotency_key="project-create-key-0001",
            actor={"email": "owner@example.com"},
        )


def test_optimistic_project_update_and_draft_lifecycle(repository):
    profile = issuer(repository)
    created = repository.create_project_with_sales_order(
        {
            "name": "Expo",
            "client_name": "Client",
            "issuer_key": profile["issuer_key"],
            "wallet": "CV HB(101)",
            "company": "HOLLA",
        },
        idempotency_key="project-create-key-0002",
        actor={"email": "owner@example.com"},
    )
    project = created["project"]
    draft = created["sales_order"]

    updated = repository.update_project(
        project["id"],
        {"status": "active", "contract_notes": "Signed"},
        expected_version=project["lock_version"],
        idempotency_key="project-update-key-0001",
        actor={"email": "owner@example.com"},
    )
    assert updated["status"] == "active"
    assert updated["lock_version"] == project["lock_version"] + 1
    with pytest.raises(ProjectDocumentConflict, match="version"):
        repository.update_project(
            project["id"],
            {"status": "completed"},
            expected_version=project["lock_version"],
            idempotency_key="project-update-key-0002",
            actor={"email": "owner@example.com"},
        )

    edited = repository.update_draft(
        draft["id"],
        {"notes": "Valid 14 days", "lines": [{"description": "Backdrop", "quantity": "2.5", "unit": "m2", "unit_price": 100000}]},
        expected_version=draft["lock_version"],
        idempotency_key="draft-update-key-0001",
        actor={"email": "owner@example.com"},
    )
    assert edited["lock_version"] == draft["lock_version"] + 1
    assert edited["lines"][0]["description"] == "Backdrop"


def test_issue_freezes_snapshot_and_pdf_and_numbers_are_atomic(repository):
    profile = issuer(repository)
    created = repository.create_project_with_sales_order(
        {"name": "Issue", "client_name": "Client", "issuer_key": profile["issuer_key"]},
        idempotency_key="project-create-key-0003",
        actor={"email": "owner@example.com"},
    )
    draft = created["sales_order"]
    snapshot = {"document_id": draft["id"], "total": 250000, "status": "issued"}
    pdf = b"%PDF-1.4\nimmutable-test\n%%EOF\n"

    issued = repository.issue_document(
        draft["id"],
        snapshot=snapshot,
        pdf_bytes=pdf,
        renderer_version="test-renderer/1",
        expected_version=draft["lock_version"],
        idempotency_key="document-issue-key-0001",
        actor={"email": "owner@example.com"},
    )

    assert issued["status"] == "issued"
    assert issued["official_number"] == "SO/HW/2026/000001"
    assert repository.get_artifact(draft["id"])["bytes"] == pdf
    with pytest.raises(ProjectDocumentConflict, match="draft"):
        repository.update_draft(
            draft["id"],
            {"notes": "mutation"},
            expected_version=issued["lock_version"],
            idempotency_key="draft-update-key-0002",
            actor={"email": "owner@example.com"},
        )

    second = repository.create_document_draft(
        created["project"]["id"],
        document_type="sales_order",
        values={},
        idempotency_key="draft-create-key-0001",
        actor={"email": "owner@example.com"},
    )
    issued_second = repository.issue_document(
        second["id"],
        snapshot={"document_id": second["id"], "total": 1},
        pdf_bytes=pdf + b"2",
        renderer_version="test-renderer/1",
        expected_version=second["lock_version"],
        idempotency_key="document-issue-key-0002",
        actor={"email": "owner@example.com"},
    )
    assert issued_second["official_number"] == "SO/HW/2026/000002"


def test_void_revision_allocations_and_audit_replay(repository):
    profile = issuer(repository)
    created = repository.create_project_with_sales_order(
        {"name": "Receipt", "client_name": "Client", "issuer_key": profile["issuer_key"]},
        idempotency_key="project-create-key-0004",
        actor={"email": "owner@example.com"},
    )
    project_id = created["project"]["id"]
    document = repository.create_document_draft(
        project_id,
        document_type="receipt",
        values={},
        idempotency_key="draft-create-key-0002",
        actor={"email": "owner@example.com"},
    )

    source_key = f"test:{uuid.uuid4()}"
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(os.environ["PROJECT_DOCUMENT_TEST_DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO financial_ledger (source_key, source_sheet, source_row, source_block, "
                "transaction_date, amount, transaction_type, company, wallet, project, is_valid, payload) "
                "VALUES (%s, 'CV HB(101)', 1, 'pemasukan', DATE '2026-11-03', 500000, 'Pemasukan', "
                "'HOLLA', 'CV HB(101)', %s, TRUE, %s)",
                (source_key, project_id, Jsonb({})),
            )

    repository.lock_allocations(
        document["id"],
        [{"ledger_source_key": source_key, "amount": 300000}],
        expected_version=document["lock_version"],
        idempotency_key="allocate-key-0001",
        actor={"email": "owner@example.com"},
    )
    loaded = repository.get_document(document["id"])
    assert loaded["allocations"][0]["amount"] == 300000

    issued = repository.issue_document(
        document["id"],
        snapshot={"document_id": document["id"], "total": 300000},
        pdf_bytes=b"%PDF immutable",
        renderer_version="test/1",
        expected_version=loaded["lock_version"],
        idempotency_key="document-issue-key-0003",
        actor={"email": "owner@example.com"},
    )
    revision = repository.revise_document(
        document["id"],
        expected_version=issued["lock_version"],
        idempotency_key="revision-key-0001",
        actor={"email": "owner@example.com"},
    )
    assert revision["revision_of_id"] == document["id"]
    assert revision["status"] == "draft"

    voided = repository.void_document(
        document["id"],
        reason="Transfer refunded",
        expected_version=issued["lock_version"],
        idempotency_key="document-void-key-0001",
        actor={"email": "owner@example.com"},
    )
    assert voided["status"] == "void"
    assert voided["void_reason"] == "Transfer refunded"
    events = repository.replay_audit(project_id=project_id)
    assert [event["event_type"] for event in events] == [
        "project.created",
        "document.created",
        "document.created",
        "document.allocations_locked",
        "document.issued",
        "document.revised",
        "document.voided",
    ]


def test_postgres_rejects_mutation_of_issued_content_artifact_and_events(repository):
    profile = issuer(repository)
    created = repository.create_project_with_sales_order(
        {"name": "Immutable", "client_name": "Client", "issuer_key": profile["issuer_key"]},
        idempotency_key="project-create-key-0005",
        actor={"email": "owner@example.com"},
    )
    draft = repository.update_draft(
        created["sales_order"]["id"],
        {"lines": [{"description": "Wall", "quantity": "1", "unit": "unit", "unit_price": 10}]},
        expected_version=created["sales_order"]["lock_version"],
        idempotency_key="immutable-draft-update-0001",
        actor={"email": "owner@example.com"},
    )
    repository.issue_document(
        draft["id"],
        snapshot={"document_id": draft["id"], "total": 10},
        pdf_bytes=b"%PDF immutable",
        renderer_version="test/1",
        expected_version=draft["lock_version"],
        idempotency_key="immutable-issue-key-0001",
        actor={"email": "owner@example.com"},
    )

    import psycopg

    dsn = os.environ["PROJECT_DOCUMENT_TEST_DATABASE_URL"]
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE project_documents SET notes = 'tampered' WHERE id = %s", (draft["id"],))
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM project_document_artifacts WHERE document_id = %s", (draft["id"],))
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM project_document_events WHERE project_id = %s",
                    (created["project"]["id"],),
                )
