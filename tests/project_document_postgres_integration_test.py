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
from flask import Flask

from dashboard_api.project_document_routes import create_project_document_blueprint
from services.project_document_repository import (
    ProjectDocumentConflict,
    ProjectDocumentRepository,
    ProjectDocumentUnavailable,
    ensure_project_document_schema,
    project_document_schema_health,
)
from services.project_documents import ProjectDocumentService


pytestmark = pytest.mark.skipif(
    not os.getenv("PROJECT_DOCUMENT_TEST_DATABASE_URL"),
    reason="PROJECT_DOCUMENT_TEST_DATABASE_URL is not configured",
)

ACTOR = {"email": "owner@example.com"}
FIXED_NOW = datetime(2026, 12, 31, 18, 30, tzinfo=ZoneInfo("UTC"))


def deterministic_renderer(snapshot):
    body = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return b"%PDF-1.7\n" + body + b"\n%%EOF\n", "test-renderer/1"


def deterministic_receipt_authority(ledger, project):
    observed = {
        "source_key": str(ledger["source_key"]),
        "source_sheet": str(ledger["source_sheet"]),
        "observed_source_row": int(ledger.get("source_row") or 0),
        "source_block": str(ledger["source_block"]),
        "message_id": str(ledger.get("message_id") or "") or None,
        "direction": str(ledger["transaction_type"]),
        "amount": int(ledger["amount"]),
        "transaction_date": str(ledger.get("transaction_date") or "") or None,
        "project_id": str(project["id"]),
        "wallet": str(project["wallet"]),
        "company": str(project["company"]),
    }
    observed["raw_cells_sha256"] = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return observed


@pytest.fixture()
def dsn():
    selected = os.environ["PROJECT_DOCUMENT_TEST_DATABASE_URL"]
    import psycopg

    migration_root = Path(__file__).parents[1] / "dashboard_api/migrations"
    project_migration = (migration_root / "003_project_documents.sql").read_text(encoding="utf-8")
    canonical_migration = (migration_root / "005_canonical_project_transactions.sql").read_text(encoding="utf-8")
    payment_migration = (migration_root / "006_invoice_payment_applications.sql").read_text(encoding="utf-8")
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
                    project_id UUID,
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
            cursor.execute(project_migration)
            cursor.execute(canonical_migration)
            cursor.execute(payment_migration)
    return selected


@pytest.fixture()
def repository(dsn):
    return ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=deterministic_renderer,
        receipt_authority_reader=deterministic_receipt_authority,
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


def project(
    repository,
    *,
    key="project-create-key-0001",
    status="planned",
    actor=ACTOR,
):
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
        actor=actor,
    )


def test_project_creation_requires_durable_wallet_company_binding(repository, dsn):
    profile = issuer(repository, key="binding-required-issuer-0001")
    with pytest.raises(ValueError, match="wallet, and company are required"):
        repository.create_project_with_sales_order(
            {
                "name": "Unbound",
                "client_name": "Client",
                "issuer_key": profile["issuer_key"],
                "wallet": "",
                "company": "",
            },
            idempotency_key="binding-required-project-0001",
            actor=ACTOR,
        )

    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO projects (
                        id, name, client_name, issuer_key, wallet, company,
                        created_by, updated_by
                    ) VALUES (
                        %s, 'Unbound SQL', 'Client', %s, '', 'HOLLA',
                        '{}'::jsonb, '{}'::jsonb
                    )
                    """,
                    (str(uuid.uuid4()), profile["issuer_key"]),
                )


def test_project_repository_rejects_unknown_issuer_and_noncanonical_mapping(repository):
    profile = issuer(repository, key="binding-canonical-issuer-0001")
    base = {
        "name": "Invalid Binding",
        "client_name": "Client",
        "issuer_key": profile["issuer_key"],
        "wallet": "CV HB(101)",
        "company": "HOLLA",
    }
    before = len(repository.list_projects())

    with pytest.raises(ValueError, match="issuer_key is not available"):
        repository.create_project_with_sales_order(
            {**base, "issuer_key": "missing"},
            idempotency_key="binding-unknown-issuer-0001",
            actor=ACTOR,
        )
    with pytest.raises(ValueError, match="wallet and company pair is unsupported"):
        repository.create_project_with_sales_order(
            {**base, "company": "TEXTURIN-Surabaya"},
            idempotency_key="binding-invalid-pair-0001",
            actor=ACTOR,
        )

    assert len(repository.list_projects()) == before


def test_project_create_http_contract_uses_production_binding_and_rejects_invalid_values(repository):
    profile = issuer(repository, key="http-binding-canonical-issuer-0001")
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        DASHBOARD_OWNER_EMAIL="owner@example.com",
        PROJECT_DOCUMENT_WRITES_ENABLED=True,
        PROJECT_DOCUMENT_READS_ENABLED=True,
    )
    app.register_blueprint(create_project_document_blueprint(repository))
    client = app.test_client()
    with client.session_transaction() as session:
        session["dashboard_user"] = "owner@example.com"
        session["dashboard_role"] = "owner"
        session["dashboard_csrf_token"] = "csrf-token"

    def headers(key):
        return {
            "Content-Type": "application/json",
            "X-CSRF-Token": "csrf-token",
            "Idempotency-Key": key,
            "If-Match": "*",
        }

    def payload(key, **changes):
        values = {
            "name": "Production Form Contract",
            "client_name": "Client",
            "issuer_key": profile["issuer_key"],
            "wallet": "CV HB(101)",
            "company": "HOLLA",
            **changes,
        }
        return {"idempotency_key": key, "values": values}

    before = len(repository.list_projects())
    created_key = "http-production-binding-0001"
    created = client.post(
        "/api/dashboard/v1/projects",
        headers=headers(created_key),
        json=payload(created_key),
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.get_json()["data"]["project"]["issuer_key"] == "hollawall"
    assert len(repository.list_projects()) == before + 1

    unknown_key = "http-unknown-issuer-0001"
    unknown = client.post(
        "/api/dashboard/v1/projects",
        headers=headers(unknown_key),
        json=payload(unknown_key, name="Unknown Issuer", issuer_key="missing"),
    )
    invalid_pair_key = "http-invalid-pair-0001"
    invalid_pair = client.post(
        "/api/dashboard/v1/projects",
        headers=headers(invalid_pair_key),
        json=payload(invalid_pair_key, name="Invalid Pair", company="TEXTURIN-Surabaya"),
    )
    assert unknown.status_code == 422
    assert invalid_pair.status_code == 422
    assert unknown.get_json()["error"]["code"] == "invalid_project_document_request"
    assert invalid_pair.get_json()["error"]["code"] == "invalid_project_document_request"
    assert len(repository.list_projects()) == before + 1


def test_project_update_rejects_noncanonical_mapping(repository):
    created = project(repository, key="update-binding-project-0001")

    with pytest.raises(ValueError, match="wallet and company pair is unsupported"):
        repository.update_project(
            created["project"]["id"],
            {"company": "TEXTURIN-Surabaya"},
            expected_version=created["project"]["lock_version"],
            idempotency_key="update-binding-invalid-0001",
            actor=ACTOR,
        )

    unchanged = repository.get_project(created["project"]["id"])
    assert unchanged["wallet"] == "CV HB(101)"
    assert unchanged["company"] == "HOLLA"


def issue(repository, document, key):
    return repository.issue_document(
        document["id"],
        expected_version=document["lock_version"],
        idempotency_key=key,
        actor=ACTOR,
    )


def receipt(repository, project_id, key):
    source_key = insert_income(
        repository._dsn,
        project_id,
        amount=1,
        source_key=f"placeholder:{uuid.uuid4()}",
    )
    return repository.create_receipt_draft(
        project_id,
        values={},
        allocations=[{"ledger_source_key": source_key, "amount": 1}],
        idempotency_key=key,
        actor=ACTOR,
    )


def insert_income(
    dsn,
    project_id,
    amount=500_000,
    source_key=None,
    *,
    wallet="CV HB(101)",
    company="HOLLA",
):
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
                    wallet, project, project_id, is_valid, payload
                ) VALUES (
                    %s, 'CV HB(101)', 1, 'pemasukan', DATE '2026-11-03',
                    %s, 'Pemasukan', %s, %s, %s, %s, TRUE, %s
                )
                """,
                (
                    selected,
                    amount,
                    company,
                    wallet,
                    project_id,
                    project_id,
                    Jsonb({"cash_authority": "sheets"}),
                ),
            )
    return selected


def set_document_total(repository, document, total, key):
    return repository.update_draft(
        document["id"],
        {
            "lines": [
                {
                    "description": "Commercial amount",
                    "quantity": 1,
                    "unit": "unit",
                    "unit_price": total,
                }
            ]
        },
        expected_version=document["lock_version"],
        idempotency_key=key,
        actor=ACTOR,
    )


def issue_sales_order(repository, created, total=1_000_000, key="sales-order-ready-0001"):
    prepared = set_document_total(
        repository,
        created["sales_order"],
        total,
        f"{key}-update",
    )
    return issue(repository, prepared, f"{key}-issue")


def invoice_with_total(repository, project_id, kind, total, key):
    values = {"invoice_kind": kind}
    if kind != "FINAL":
        values["lines"] = [
            {
                "description": kind,
                "quantity": "1",
                "unit": "termin",
                "unit_price": total,
            }
        ]
    draft = repository.create_invoice_draft(
        project_id,
        values=values,
        idempotency_key=f"{key}-create",
        actor=ACTOR,
    )
    current_total = int(repository._calculate_totals(draft)["total"])
    if current_total != total:
        return set_document_total(repository, draft, total, f"{key}-update")
    return draft


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


def test_issuer_non_code_update_passes_and_original_update_replays(repository):
    first = issuer(repository)
    updated = repository.upsert_issuer_profile(
        issuer_key=first["issuer_key"],
        legal_name="CV Holla Berkreasi Updated",
        display_name="Hollawall Studio",
        number_code="HW",
        address="Surabaya Updated",
        phone="+628123456789",
        actor=ACTOR,
        expected_version=first["profile_version"],
        idempotency_key="issuer-legitimate-update-0001",
    )
    replay = repository.upsert_issuer_profile(
        issuer_key=first["issuer_key"],
        legal_name="CV Holla Berkreasi Updated",
        display_name="Hollawall Studio",
        number_code="HW",
        address="Surabaya Updated",
        phone="+628123456789",
        actor=ACTOR,
        expected_version=first["profile_version"],
        idempotency_key="issuer-legitimate-update-0001",
    )

    assert replay == updated
    assert updated["profile_version"] == 2
    assert updated["display_name"] == "Hollawall Studio"
    assert updated["number_code"] == "HW"


def test_issuer_code_rotation_is_rejected_and_historical_code_stays_reserved(repository):
    first = issuer(repository)

    with pytest.raises(
        ProjectDocumentConflict,
        match="number_code is immutable after profile creation",
    ):
        repository.upsert_issuer_profile(
            issuer_key=first["issuer_key"],
            legal_name=first["legal_name"],
            display_name=first["display_name"],
            number_code="NEW",
            address=first["address"],
            actor=ACTOR,
            expected_version=first["profile_version"],
            idempotency_key="issuer-code-rotation-0001",
        )

    unchanged = repository.get_issuer_profile(first["issuer_key"])
    assert unchanged["number_code"] == "HW"
    assert unchanged["profile_version"] == 1
    with pytest.raises(ProjectDocumentConflict, match="number_code"):
        issuer(repository, issuer_key="other", number_code="HW")


def test_direct_sql_issuer_code_mutation_is_rejected(repository, dsn):
    import psycopg

    issuer(repository)
    with pytest.raises(
        psycopg.errors.RaiseException,
        match="number_code is immutable after profile creation",
    ):
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE project_issuer_profiles SET number_code = 'NEW' "
                    "WHERE issuer_key = 'hollawall'"
                )


def test_rejected_issuer_code_rotation_does_not_interrupt_numbering(repository):
    created = project(repository)
    first = issue_sales_order(
        repository,
        created,
        total=1_000_000,
        key="immutable-code-numbering-first-0001",
    )
    profile = repository.get_issuer_profile("hollawall")
    with pytest.raises(ProjectDocumentConflict, match="number_code is immutable"):
        repository.upsert_issuer_profile(
            issuer_key="hollawall",
            legal_name=profile["legal_name"],
            display_name=profile["display_name"],
            number_code="NEW",
            address=profile["address"],
            actor=ACTOR,
            expected_version=profile["profile_version"],
            idempotency_key="immutable-code-numbering-rotate-0001",
        )
    second_project = project(
        repository,
        key="immutable-code-numbering-second-project-0001",
    )
    second = issue_sales_order(
        repository,
        second_project,
        total=1_000_000,
        key="immutable-code-numbering-second-0001",
    )

    assert first["official_number"] == "SO/HW/2027/000001"
    assert second["official_number"] == "SO/HW/2027/000002"


def test_project_creation_defaults_and_invoice_status_restrictions(repository):
    created = project(repository)
    sales_order = created["sales_order"]
    assert sales_order["issue_date"] == "2027-01-01"
    assert sales_order["valid_until"] == "2027-01-15"

    issue_sales_order(
        repository,
        created,
        1_000_000,
        "invoice-defaults-sales-order-0001",
    )
    invoice = repository.create_invoice_draft(
        created["project"]["id"],
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


def test_sales_order_with_zero_lines_is_rejected_before_numbering_and_rendering(dsn):
    rendered_types = []

    def tracking_renderer(snapshot):
        rendered_types.append(snapshot["document"]["document_type"])
        return deterministic_renderer(snapshot)

    repository = ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=tracking_renderer,
    )
    created = project(repository, key="empty-sales-order-project-0001")
    empty = created["sales_order"]

    with pytest.raises(ProjectDocumentConflict, match="at least one line"):
        issue(repository, empty, "empty-sales-order-issue-0001")

    assert rendered_types == []
    prepared = set_document_total(
        repository,
        empty,
        1_000_000,
        "empty-sales-order-update-0001",
    )
    issued = issue(repository, prepared, "empty-sales-order-retry-0001")

    assert issued["official_number"] == "SO/HW/2027/000001"
    assert rendered_types == ["sales_order"]


def test_invoice_with_zero_lines_is_rejected_before_numbering_and_rendering(dsn):
    rendered_types = []

    def tracking_renderer(snapshot):
        rendered_types.append(snapshot["document"]["document_type"])
        return deterministic_renderer(snapshot)

    repository = ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=tracking_renderer,
    )
    created = project(repository, key="empty-invoice-project-0001")
    project_id = created["project"]["id"]
    issue_sales_order(
        repository,
        created,
        1_000_000,
        "empty-invoice-sales-order-0001",
    )
    created_invoice = repository.create_invoice_draft(
        project_id,
        values={"invoice_kind": "DP"},
        idempotency_key="empty-invoice-create-0001",
        actor=ACTOR,
    )
    empty = repository.update_draft(
        created_invoice["id"],
        {"lines": []},
        expected_version=created_invoice["lock_version"],
        idempotency_key="empty-invoice-clear-lines-0001",
        actor=ACTOR,
    )

    with pytest.raises(ProjectDocumentConflict, match="at least one line"):
        issue(repository, empty, "empty-invoice-issue-0001")

    assert rendered_types == ["sales_order"]
    prepared = set_document_total(
        repository,
        empty,
        300_000,
        "empty-invoice-update-0001",
    )
    issued = issue(repository, prepared, "empty-invoice-retry-0001")

    assert issued["official_number"] == "INV/HW/2027/000001"
    assert rendered_types == ["sales_order", "invoice"]


def test_canonical_issuance_renders_locked_state_and_persists_exact_bytes(repository):
    created = project(repository)
    draft = repository.update_draft(
        created["sales_order"]["id"],
        {
            "document_discount_percent": "10",
            "tax_percent": "2",
            "prepared_by": "Naufal",
            "client_signatory": "PT Client",
            "project_image_url": "data:image/png;base64,Zm9v",
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
    assert snapshot["document"]["prepared_by"] == "Naufal"
    assert snapshot["document"]["client_signatory"] == "PT Client"
    assert snapshot["document"]["project_image_url"] == "data:image/png;base64,Zm9v"
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


def test_document_metadata_round_trips_and_rejects_unsafe_project_images(repository):
    created = project(repository, key="document-metadata-project-0001")
    draft = created["sales_order"]
    updated = repository.update_draft(
        draft["id"],
        {
            "prepared_by": "Naufal",
            "client_signatory": "PT Client",
            "project_image_url": "data:image/jpeg;base64,Zm9v",
        },
        expected_version=draft["lock_version"],
        idempotency_key="document-metadata-update-0001",
        actor=ACTOR,
    )
    assert updated["prepared_by"] == "Naufal"
    assert updated["client_signatory"] == "PT Client"
    assert updated["project_image_url"] == "data:image/jpeg;base64,Zm9v"

    for key, image in (
        ("remote", "https://example.com/project.png"),
        ("oversize", f"data:image/png;base64,{'A' * 196_609}"),
    ):
        with pytest.raises(ValueError, match="project_image_url"):
            repository.update_draft(
                draft["id"],
                {"project_image_url": image},
                expected_version=updated["lock_version"],
                idempotency_key=f"document-metadata-{key}-0001",
                actor=ACTOR,
            )


def test_migration_upgrades_pre_release_003_metadata_columns(repository, dsn):
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE project_documents DROP CONSTRAINT "
                "project_documents_project_image_url_check"
            )
            cursor.execute(
                "ALTER TABLE project_documents DROP COLUMN prepared_by, "
                "DROP COLUMN client_signatory, DROP COLUMN project_image_url"
            )

    health = ensure_project_document_schema(dsn)
    assert health["ready"] is True
    assert repository.get_document(project(repository)["sales_order"]["id"])["prepared_by"] is None


def test_renderer_failure_and_invalid_pdf_roll_back_number_and_issuance(dsn):
    failing = ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=lambda _snapshot: (_ for _ in ()).throw(RuntimeError("renderer failed")),
    )
    created = project(failing)
    draft = set_document_total(
        failing,
        created["sales_order"],
        1_000_000,
        "document-issue-failure-prepare-0001",
    )
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
    second_project = project(repository, key="concurrent-second-project-0001")
    first = set_document_total(
        repository,
        created["sales_order"],
        1_000_000,
        "concurrent-first-prepare-0001",
    )
    second = set_document_total(
        repository,
        second_project["sales_order"],
        2_000_000,
        "concurrent-second-prepare-0001",
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
                    (first, "concurrent-issue-key-0001"),
                    (second, "concurrent-issue-key-0002"),
                ],
            )
        )
    assert {item["official_number"] for item in results} == {
        "SO/HW/2027/000001",
        "SO/HW/2027/000002",
    }

    # Two independent transactions with one key converge on the committed response.
    third_project = project(repository, key="concurrent-third-project-0001")
    third = set_document_total(
        repository,
        third_project["sales_order"],
        3_000_000,
        "concurrent-third-prepare-0001",
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


def test_service_creates_receipt_and_authority_evidence_atomically(repository, dsn):
    created = project(repository)
    project_id = created["project"]["id"]
    source_key = insert_income(dsn, project_id, amount=500_000)
    second_source_key = insert_income(dsn, project_id, amount=100_000)
    subject = ProjectDocumentService(repository)

    allocations = [
        {"ledger_source_key": source_key, "amount": 200_000},
        {"ledger_source_key": second_source_key, "amount": 100_000},
    ]
    draft = subject.create_receipt(
        project_id,
        allocations=allocations,
        values={"notes": "Pembayaran DP"},
        idempotency_key="atomic-receipt-create-0001",
        actor=ACTOR,
    )
    replay = subject.create_receipt(
        project_id,
        allocations=list(reversed(allocations)),
        values={
            "notes": "Pembayaran DP",
            "document_discount_amount": 0,
            "document_discount_percent": "0",
            "tax_percent": "0",
        },
        idempotency_key="atomic-receipt-create-0001",
        actor=ACTOR,
    )

    assert replay == draft
    assert draft["document_type"] == "receipt"
    assert draft["lines"][0]["line_total"] == 300_000
    assert sum(item["amount"] for item in draft["allocations"]) == 300_000
    assert {
        item["ledger_snapshot"]["draft_authority"]["source_key"]
        for item in draft["allocations"]
    } == {source_key, second_source_key}

    issued = subject.issue_document(
        draft["id"],
        expected_version=draft["lock_version"],
        idempotency_key="atomic-receipt-issue-0001",
        actor=ACTOR,
    )
    assert issued["official_number"] == "KWT/HW/2027/000001"
    allocation_snapshots = [
        item["ledger_snapshot"]
        for item in issued["immutable_snapshot"]["allocations"]
    ]
    assert {
        snapshot["draft_authority"]["source_key"]
        for snapshot in allocation_snapshots
    } == {source_key, second_source_key}
    assert {
        snapshot["issue_authority"]["source_key"]
        for snapshot in allocation_snapshots
    } == {source_key, second_source_key}
    assert issued["immutable_snapshot"]["totals"]["total"] == 300_000


def test_receipt_sheet_drift_or_missing_reader_fails_closed_before_issue(repository, dsn):
    created = project(repository)
    project_id = created["project"]["id"]
    source_key = insert_income(dsn, project_id, amount=500_000)
    state = {"available": True, "render_calls": 0}

    def authority(ledger, project_row):
        if not state["available"]:
            raise ProjectDocumentConflict("authoritative receipt source no longer exists")
        return deterministic_receipt_authority(ledger, project_row)

    def renderer(snapshot):
        state["render_calls"] += 1
        return deterministic_renderer(snapshot)

    local = ProjectDocumentRepository(
        dsn,
        now=lambda: FIXED_NOW,
        renderer=renderer,
        receipt_authority_reader=authority,
    )
    subject = ProjectDocumentService(local)
    draft = subject.create_receipt(
        project_id,
        allocations=[{"ledger_source_key": source_key, "amount": 200_000}],
        values={},
        idempotency_key="drift-receipt-create-0001",
        actor=ACTOR,
    )
    state["available"] = False

    with pytest.raises(ProjectDocumentConflict, match="no longer exists"):
        subject.issue_document(
            draft["id"],
            expected_version=draft["lock_version"],
            idempotency_key="drift-receipt-issue-0001",
            actor=ACTOR,
        )
    assert state["render_calls"] == 0
    assert local.get_document(draft["id"])["status"] == "draft"
    assert local.get_document(draft["id"])["official_number"] is None

    unavailable = ProjectDocumentRepository(
        dsn,
        renderer=deterministic_renderer,
    )
    with pytest.raises(ProjectDocumentUnavailable, match="authority reader"):
        ProjectDocumentService(unavailable).create_receipt(
            project_id,
            allocations=[{"ledger_source_key": source_key, "amount": 100_000}],
            values={},
            idempotency_key="missing-reader-receipt-create-0001",
            actor=ACTOR,
        )


def test_draft_allocations_reserve_income_and_concurrent_overreservation_fails(repository, dsn):
    created = project(repository)
    project_id = created["project"]["id"]
    first = receipt(repository, project_id, "receipt-create-key-0001")
    second = receipt(repository, project_id, "receipt-create-key-0002")
    source_key = insert_income(dsn, project_id)
    barrier = threading.Barrier(2)

    def allocate(document, key):
        local = ProjectDocumentRepository(
            dsn,
            renderer=deterministic_renderer,
            receipt_authority_reader=deterministic_receipt_authority,
        )
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


@pytest.mark.parametrize(
    ("wallet", "company"),
    [
        (None, "HOLLA"),
        ("CV HB(101)", None),
        ("", "HOLLA"),
        ("CV HB(101)", ""),
    ],
)
def test_project_update_preserves_non_empty_wallet_company_binding(
    repository, dsn, wallet, company
):
    created = project(repository)
    project_id = created["project"]["id"]

    with pytest.raises(ValueError, match="wallet and company must remain non-empty"):
        repository.update_project(
            project_id,
            {"wallet": wallet, "company": company},
            expected_version=created["project"]["lock_version"],
            idempotency_key=f"missing-mapping-{wallet!s}-{company!s}-0001".replace(" ", "-"),
            actor=ACTOR,
        )

    current = repository.get_project(project_id)
    assert current["wallet"] == "CV HB(101)"
    assert current["company"] == "HOLLA"


@pytest.mark.parametrize(
    ("ledger_wallet", "ledger_company", "message"),
    [
        ("OTHER", "HOLLA", "issuer wallet does not match"),
        ("CV HB(101)", "OTHER", "issuer company does not match"),
    ],
)
def test_receipt_allocation_requires_exact_project_ledger_mapping(
    repository, dsn, ledger_wallet, ledger_company, message
):
    created = project(repository)
    project_id = created["project"]["id"]
    draft = receipt(repository, project_id, f"mismatch-receipt-{uuid.uuid4()}")
    source_key = insert_income(
        dsn,
        project_id,
        wallet=ledger_wallet,
        company=ledger_company,
    )

    with pytest.raises(ProjectDocumentConflict, match=message):
        repository.lock_allocations(
            draft["id"],
            [{"ledger_source_key": source_key, "amount": 100_000}],
            expected_version=draft["lock_version"],
            idempotency_key=f"mismatch-allocation-{uuid.uuid4()}",
            actor=ACTOR,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"wallet": "OTHER"}, "issuer wallet does not match"),
        ({"company": "OTHER"}, "issuer company does not match"),
    ],
)
def test_receipt_issue_revalidates_complete_exact_project_ledger_mapping(
    repository, dsn, changes, message
):
    created = project(repository)
    project_id = created["project"]["id"]
    draft = receipt(repository, project_id, f"issue-mapping-receipt-{uuid.uuid4()}")
    source_key = insert_income(dsn, project_id)
    allocated = repository.lock_allocations(
        draft["id"],
        [{"ledger_source_key": source_key, "amount": 100_000}],
        expected_version=draft["lock_version"],
        idempotency_key=f"issue-mapping-allocation-{uuid.uuid4()}",
        actor=ACTOR,
    )
    # Simulate out-of-band database corruption. The public repository now rejects
    # these invalid mappings before SQL, while issue-time defense must still fail closed.
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            if "wallet" in changes:
                cursor.execute("UPDATE projects SET wallet = %s WHERE id = %s", (changes["wallet"], project_id))
            else:
                cursor.execute("UPDATE projects SET company = %s WHERE id = %s", (changes["company"], project_id))

    with pytest.raises(ProjectDocumentConflict, match=message):
        issue(repository, allocated, f"issue-mapping-attempt-{uuid.uuid4()}")
    assert repository.get_document(allocated["id"])["status"] == "draft"


def test_receipt_revision_is_rejected_with_correction_path(repository, dsn):
    created = project(repository)
    project_id = created["project"]["id"]
    draft = receipt(repository, project_id, "receipt-not-revisable-create-0001")
    source_key = insert_income(dsn, project_id)
    allocated = repository.lock_allocations(
        draft["id"],
        [{"ledger_source_key": source_key, "amount": 100_000}],
        expected_version=draft["lock_version"],
        idempotency_key="receipt-not-revisable-allocate-0001",
        actor=ACTOR,
    )
    issued = issue(repository, allocated, "receipt-not-revisable-issue-0001")

    with pytest.raises(
        ProjectDocumentConflict,
        match="payment reversal, receipt void, and a new receipt",
    ):
        repository.revise_document(
            issued["id"],
            expected_version=issued["lock_version"],
            idempotency_key="receipt-not-revisable-revise-0001",
            actor=ACTOR,
        )
    assert repository.get_document(issued["id"])["status"] == "issued"


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
        dsn,
        now=lambda: FIXED_NOW,
        renderer=blocking_renderer,
        receipt_authority_reader=deterministic_receipt_authority,
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


def test_final_command_requires_one_active_issued_sales_order(repository):
    created = project(repository)
    project_id = created["project"]["id"]

    with pytest.raises(
        ProjectDocumentConflict,
        match="exactly one active issued Sales Order",
    ):
        repository.create_invoice_draft(
            project_id,
            values={"invoice_kind": "FINAL"},
            idempotency_key="final-no-sales-order-0001",
            actor=ACTOR,
        )

    first_sales_order = issue_sales_order(
        repository, created, key="multiple-sales-order-first-0001"
    )
    second_sales_order = repository.create_document_draft(
        project_id,
        document_type="sales_order",
        values={},
        idempotency_key="multiple-sales-order-second-create-0001",
        actor=ACTOR,
    )
    second_sales_order = set_document_total(
        repository,
        second_sales_order,
        1_000_000,
        "multiple-sales-order-second-update-0001",
    )
    with pytest.raises(ProjectDocumentConflict, match="active issued Sales Order"):
        issue(repository, second_sales_order, "multiple-sales-order-second-issue-0001")
    assert repository.get_document(first_sales_order["id"])["status"] == "issued"


def test_sales_order_revision_and_void_preserve_issued_invoice_coverage(repository):
    created = project(repository, key="sales-order-transition-project-0001")
    issued_sales_order = issue_sales_order(
        repository, created, 1_000_000, "sales-order-transition-original-0001"
    )
    dp = invoice_with_total(
        repository,
        created["project"]["id"],
        "DP",
        600_000,
        "sales-order-transition-dp-0001",
    )
    issue(repository, dp, "sales-order-transition-dp-issue-0001")
    revision = repository.revise_document(
        issued_sales_order["id"],
        expected_version=issued_sales_order["lock_version"],
        idempotency_key="sales-order-transition-revise-0001",
        actor=ACTOR,
    )
    lowered = set_document_total(
        repository,
        revision,
        500_000,
        "sales-order-transition-lower-0001",
    )

    with pytest.raises(ProjectDocumentConflict, match="issued invoice total"):
        issue(repository, lowered, "sales-order-transition-revision-issue-0001")
    with pytest.raises(ProjectDocumentConflict, match="issued invoices exist"):
        repository.void_document(
            issued_sales_order["id"],
            reason="Invalid cancellation",
            expected_version=issued_sales_order["lock_version"],
            idempotency_key="sales-order-transition-void-0001",
            actor=ACTOR,
        )


def test_sales_order_revision_cannot_change_total_while_final_is_active(repository):
    created = project(repository, key="final-locks-sales-order-project-0001")
    project_id = created["project"]["id"]
    original = issue_sales_order(
        repository,
        created,
        1_000_000,
        "final-locks-sales-order-original-0001",
    )
    final = invoice_with_total(
        repository,
        project_id,
        "FINAL",
        1_000_000,
        "final-locks-sales-order-final-0001",
    )
    issue(repository, final, "final-locks-sales-order-final-issue-0001")
    revision = repository.revise_document(
        original["id"],
        expected_version=original["lock_version"],
        idempotency_key="final-locks-sales-order-revise-0001",
        actor=ACTOR,
    )
    changed = set_document_total(
        repository,
        revision,
        1_100_000,
        "final-locks-sales-order-change-total-0001",
    )

    with pytest.raises(
        ProjectDocumentConflict,
        match="Sales Order total is immutable while an active FINAL invoice exists",
    ):
        issue(repository, changed, "final-locks-sales-order-issue-0001")


def test_sales_order_metadata_only_revision_is_allowed_while_final_is_active(repository):
    created = project(repository, key="final-allows-sales-order-metadata-project-0001")
    project_id = created["project"]["id"]
    original = issue_sales_order(
        repository,
        created,
        1_000_000,
        "final-allows-sales-order-metadata-original-0001",
    )
    final = invoice_with_total(
        repository,
        project_id,
        "FINAL",
        1_000_000,
        "final-allows-sales-order-metadata-final-0001",
    )
    issue(repository, final, "final-allows-sales-order-metadata-final-issue-0001")
    revision = repository.revise_document(
        original["id"],
        expected_version=original["lock_version"],
        idempotency_key="final-allows-sales-order-metadata-revise-0001",
        actor=ACTOR,
    )
    metadata_only = repository.update_draft(
        revision["id"],
        {"notes": "Corrected delivery contact"},
        expected_version=revision["lock_version"],
        idempotency_key="final-allows-sales-order-metadata-update-0001",
        actor=ACTOR,
    )

    replacement = issue(
        repository,
        metadata_only,
        "final-allows-sales-order-metadata-issue-0001",
    )

    assert replacement["status"] == "issued"
    assert replacement["immutable_snapshot"]["totals"]["total"] == 1_000_000
    assert replacement["notes"] == "Corrected delivery contact"


def test_project_issuer_is_immutable_once_the_sales_order_draft_exists(repository):
    created = project(repository, key="issuer-binding-project-0001")
    alternate = issuer(
        repository,
        issuer_key="alternate",
        number_code="ALT",
        key="issuer-binding-alternate-0001",
    )

    with pytest.raises(
        ProjectDocumentConflict,
        match="issuer_key is immutable after the document chain is created",
    ):
        repository.update_project(
            created["project"]["id"],
            {"issuer_key": alternate["issuer_key"]},
            expected_version=created["project"]["lock_version"],
            idempotency_key="issuer-binding-project-update-0001",
            actor=ACTOR,
        )


def test_project_issuer_is_immutable_after_any_document_is_issued(repository):
    created = project(repository, key="issuer-immutable-project-0001")
    alternate = issuer(
        repository,
        issuer_key="alternate",
        number_code="ALT",
        key="issuer-immutable-alternate-0001",
    )
    issue_sales_order(
        repository,
        created,
        1_000_000,
        "issuer-immutable-sales-order-0001",
    )

    with pytest.raises(
        ProjectDocumentConflict,
        match="issuer_key is immutable after the document chain is created",
    ):
        repository.update_project(
            created["project"]["id"],
            {"issuer_key": alternate["issuer_key"]},
            expected_version=created["project"]["lock_version"],
            idempotency_key="issuer-immutable-project-update-0001",
            actor=ACTOR,
        )


def test_invoice_draft_requires_active_sales_order_issuer_to_match_project(repository, dsn):
    import psycopg

    created = project(repository, key="invoice-draft-issuer-project-0001")
    alternate = issuer(
        repository,
        issuer_key="alternate",
        number_code="ALT",
        key="invoice-draft-issuer-alternate-0001",
    )
    issue_sales_order(
        repository,
        created,
        1_000_000,
        "invoice-draft-issuer-sales-order-0001",
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET issuer_key = %s WHERE id = %s",
                (alternate["issuer_key"], created["project"]["id"]),
            )

    with pytest.raises(
        ProjectDocumentConflict,
        match="active issued Sales Order issuer must match project issuer",
    ):
        repository.create_invoice_draft(
            created["project"]["id"],
            values={
                "invoice_kind": "DP",
                "lines": [{
                    "description": "DP",
                    "quantity": "1",
                    "unit": "termin",
                    "unit_price": 100_000,
                }],
            },
            idempotency_key="invoice-draft-issuer-create-0001",
            actor=ACTOR,
        )


def test_invoice_issue_revalidates_active_sales_order_project_and_document_issuer(
    repository,
    dsn,
):
    import psycopg

    created = project(repository, key="invoice-issue-issuer-project-0001")
    alternate = issuer(
        repository,
        issuer_key="alternate",
        number_code="ALT",
        key="invoice-issue-issuer-alternate-0001",
    )
    issue_sales_order(
        repository,
        created,
        1_000_000,
        "invoice-issue-issuer-sales-order-0001",
    )
    invoice = repository.create_invoice_draft(
        created["project"]["id"],
        values={
            "invoice_kind": "DP",
            "lines": [{
                "description": "DP",
                "quantity": "1",
                "unit": "termin",
                "unit_price": 100_000,
            }],
        },
        idempotency_key="invoice-issue-issuer-create-0001",
        actor=ACTOR,
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET issuer_key = %s WHERE id = %s",
                (alternate["issuer_key"], created["project"]["id"]),
            )

    with pytest.raises(
        ProjectDocumentConflict,
        match="active issued Sales Order issuer must match project and invoice issuer",
    ):
        issue(repository, invoice, "invoice-issue-issuer-command-0001")


def test_project_create_replay_ignores_actor_enrichment(repository):
    first = project(
        repository,
        key="actor-stable-project-0001",
        actor={"email": "owner@example.com"},
    )
    replay = project(
        repository,
        key="actor-stable-project-0001",
        actor={"email": "owner@example.com", "role": "owner"},
    )

    assert replay == first


def test_final_issue_equals_residual_after_dp_and_progress(repository):
    created = project(repository)
    project_id = created["project"]["id"]
    issue_sales_order(repository, created, 1_000_000, "residual-sales-order-0001")
    dp = invoice_with_total(repository, project_id, "DP", 300_000, "residual-dp-0001")
    progress = invoice_with_total(
        repository, project_id, "PROGRESS", 200_000, "residual-progress-0001"
    )
    issue(repository, dp, "residual-dp-issue-0001")
    issue(repository, progress, "residual-progress-issue-0001")
    final = repository.create_invoice_draft(
        project_id,
        values={"invoice_kind": "FINAL"},
        idempotency_key="residual-final-0001",
        actor=ACTOR,
    )
    issued = issue(repository, final, "residual-final-issue-0001")
    assert issued["immutable_snapshot"]["totals"]["total"] == 500_000


def test_final_rejects_monetary_draft_updates_and_issue_revalidates_shape(repository, dsn):
    import psycopg

    created = project(repository)
    project_id = created["project"]["id"]
    issue_sales_order(repository, created, 1_000, "final-shape-sales-order-0001")
    final = repository.create_invoice_draft(
        project_id,
        values={"invoice_kind": "FINAL"},
        idempotency_key="final-shape-create-0001",
        actor=ACTOR,
    )

    with pytest.raises(ProjectDocumentConflict, match="FINAL monetary fields"):
        repository.update_draft(
            final["id"],
            {"tax_percent": "10"},
            expected_version=final["lock_version"],
            idempotency_key="final-shape-update-0001",
            actor=ACTOR,
        )

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE project_documents SET tax_percent = 10 WHERE id = %s",
                (final["id"],),
            )
            cursor.execute(
                """
                UPDATE project_document_lines
                SET unit_price = 909, line_gross = 909,
                    line_discount = 0, line_total = 909
                WHERE document_id = %s
                """,
                (final["id"],),
            )

    with pytest.raises(ProjectDocumentConflict, match="FINAL invoice cannot add"):
        issue(repository, final, "final-shape-issue-0001")


def test_concurrent_dp_and_stale_final_issue_serialize_without_overbilling(repository, dsn):
    created = project(repository)
    project_id = created["project"]["id"]
    sales_order = set_document_total(
        repository,
        created["sales_order"],
        1_000_000,
        "concurrent-commercial-so-update-0001",
    )
    issue(repository, sales_order, "concurrent-commercial-so-issue-0001")
    subject = ProjectDocumentService(repository)
    dp = subject.create_invoice(
        project_id,
        kind="DP",
        values={
            "lines": [
                {
                    "description": "DP",
                    "quantity": "1",
                    "unit": "termin",
                    "unit_price": 500_000,
                }
            ]
        },
        idempotency_key="concurrent-commercial-dp-create-0001",
        actor=ACTOR,
    )
    stale_final = subject.create_invoice(
        project_id,
        kind="FINAL",
        values={},
        idempotency_key="concurrent-commercial-final-create-0001",
        actor=ACTOR,
    )
    barrier = threading.Barrier(2)

    def issue_local(document, key):
        local = ProjectDocumentRepository(
            dsn,
            now=lambda: FIXED_NOW,
            renderer=deterministic_renderer,
        )
        barrier.wait(timeout=5)
        return issue(local, document, key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(
                issue_local,
                dp,
                "concurrent-commercial-dp-issue-0001",
            ),
            executor.submit(
                issue_local,
                stale_final,
                "concurrent-commercial-final-issue-0001",
            ),
        )
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except ProjectDocumentConflict as exc:
                outcomes.append(exc)

    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum(isinstance(item, ProjectDocumentConflict) for item in outcomes) == 1
    documents = repository.list_documents(project_id)
    issued_invoices = [
        item
        for item in documents
        if item["document_type"] == "invoice" and item["status"] == "issued"
    ]
    assert len(issued_invoices) == 1
    assert issued_invoices[0]["immutable_snapshot"]["totals"]["total"] <= 1_000_000


def test_progress_issue_rejects_overbilling_immediately(repository):
    created = project(repository)
    project_id = created["project"]["id"]
    issue_sales_order(repository, created, 1_000_000, "overbilled-sales-order-0001")
    dp = invoice_with_total(repository, project_id, "DP", 700_000, "overbilled-dp-0001")
    progress = invoice_with_total(
        repository, project_id, "PROGRESS", 400_000, "overbilled-progress-0001"
    )
    issue(repository, dp, "overbilled-dp-issue-0001")

    with pytest.raises(
        ProjectDocumentConflict,
        match="invoice total exceeds residual commercial amount 300000",
    ):
        issue(repository, progress, "overbilled-progress-issue-0001")


def test_final_residual_excludes_void_invoices_and_requires_non_void_sales_order(repository):
    created = project(repository)
    project_id = created["project"]["id"]
    sales_order = issue_sales_order(
        repository, created, 1_000_000, "void-residual-sales-order-0001"
    )
    dp = invoice_with_total(repository, project_id, "DP", 300_000, "void-residual-dp-0001")
    issued_dp = issue(repository, dp, "void-residual-dp-issue-0001")
    repository.void_document(
        issued_dp["id"],
        reason="Payment cancelled",
        expected_version=issued_dp["lock_version"],
        idempotency_key="void-residual-dp-void-0001",
        actor=ACTOR,
    )
    final = invoice_with_total(
        repository, project_id, "FINAL", 1_000_000, "void-residual-final-0001"
    )
    issued_final = issue(repository, final, "void-residual-final-issue-0001")
    assert issued_final["status"] == "issued"

    with pytest.raises(ProjectDocumentConflict, match="issued invoices exist"):
        repository.void_document(
            sales_order["id"],
            reason="Commercial order cancelled",
            expected_version=sales_order["lock_version"],
            idempotency_key="void-residual-sales-order-blocked-0001",
            actor=ACTOR,
        )
    repository.void_document(
        issued_final["id"],
        reason="Payment cancelled",
        expected_version=issued_final["lock_version"],
        idempotency_key="void-residual-final-void-0001",
        actor=ACTOR,
    )
    repository.void_document(
        sales_order["id"],
        reason="Commercial order cancelled",
        expected_version=sales_order["lock_version"],
        idempotency_key="void-residual-sales-order-void-0001",
        actor=ACTOR,
    )
    with pytest.raises(
        ProjectDocumentConflict,
        match="exactly one active issued Sales Order",
    ):
        repository.create_invoice_draft(
            project_id,
            values={"invoice_kind": "FINAL"},
            idempotency_key="void-residual-replacement-0001",
            actor=ACTOR,
        )


@pytest.mark.parametrize("invoice_kind", ["DP", "PROGRESS"])
def test_dp_and_progress_cannot_be_voided_until_active_final_is_voided(
    repository,
    invoice_kind,
):
    created = project(
        repository,
        key=f"final-blocks-{invoice_kind.lower()}-void-project-0001",
    )
    project_id = created["project"]["id"]
    issue_sales_order(
        repository,
        created,
        1_000_000,
        f"final-blocks-{invoice_kind.lower()}-void-sales-order-0001",
    )
    earlier = invoice_with_total(
        repository,
        project_id,
        invoice_kind,
        300_000,
        f"final-blocks-{invoice_kind.lower()}-void-earlier-0001",
    )
    issued_earlier = issue(
        repository,
        earlier,
        f"final-blocks-{invoice_kind.lower()}-void-earlier-issue-0001",
    )
    final = invoice_with_total(
        repository,
        project_id,
        "FINAL",
        700_000,
        f"final-blocks-{invoice_kind.lower()}-void-final-0001",
    )
    issued_final = issue(
        repository,
        final,
        f"final-blocks-{invoice_kind.lower()}-void-final-issue-0001",
    )

    with pytest.raises(
        ProjectDocumentConflict,
        match="active FINAL invoice must be voided first",
    ):
        repository.void_document(
            issued_earlier["id"],
            reason="Commercial correction",
            expected_version=issued_earlier["lock_version"],
            idempotency_key=f"final-blocks-{invoice_kind.lower()}-void-blocked-0001",
            actor=ACTOR,
        )

    assert repository.get_document(issued_earlier["id"])["status"] == "issued"
    repository.void_document(
        issued_final["id"],
        reason="Commercial correction",
        expected_version=issued_final["lock_version"],
        idempotency_key=f"final-blocks-{invoice_kind.lower()}-void-final-void-0001",
        actor=ACTOR,
    )
    voided = repository.void_document(
        issued_earlier["id"],
        reason="Commercial correction",
        expected_version=issued_earlier["lock_version"],
        idempotency_key=f"final-blocks-{invoice_kind.lower()}-void-after-final-0001",
        actor=ACTOR,
    )

    assert voided["status"] == "void"


def test_final_residual_counts_only_active_invoice_revision(repository):
    created = project(repository)
    project_id = created["project"]["id"]
    issue_sales_order(repository, created, 1_000_000, "chain-sales-order-0001")
    dp = invoice_with_total(repository, project_id, "DP", 300_000, "chain-dp-0001")
    issued_dp = issue(repository, dp, "chain-dp-issue-0001")
    revised_dp = repository.revise_document(
        issued_dp["id"],
        expected_version=issued_dp["lock_version"],
        idempotency_key="chain-dp-revise-0001",
        actor=ACTOR,
    )
    revised_dp = set_document_total(
        repository, revised_dp, 350_000, "chain-dp-revision-update-0001"
    )
    issue(repository, revised_dp, "chain-dp-revision-issue-0001")
    final = invoice_with_total(
        repository, project_id, "FINAL", 650_000, "chain-final-0001"
    )
    issued_final = issue(repository, final, "chain-final-issue-0001")
    assert issued_final["status"] == "issued"

    final_revision = repository.revise_document(
        issued_final["id"],
        expected_version=issued_final["lock_version"],
        idempotency_key="chain-final-revise-0001",
        actor=ACTOR,
    )
    replacement = issue(repository, final_revision, "chain-final-revision-issue-0001")
    assert replacement["status"] == "issued"


def test_revision_issue_emits_mutual_superseded_and_issued_events_once(repository):
    created = project(repository)
    original = issue_sales_order(
        repository, created, 1_000_000, "event-sales-order-0001"
    )
    revision = repository.revise_document(
        original["id"],
        expected_version=original["lock_version"],
        idempotency_key="event-sales-order-revise-0001",
        actor=ACTOR,
    )
    replacement = issue(repository, revision, "event-sales-order-revision-issue-0001")
    replay = issue(repository, revision, "event-sales-order-revision-issue-0001")
    assert replay == replacement

    expected_links = {
        "original_document_id": original["id"],
        "original_official_number": original["official_number"],
        "replacement_document_id": replacement["id"],
        "replacement_official_number": replacement["official_number"],
    }
    original_events = repository.replay_audit(document_id=original["id"])
    replacement_events = repository.replay_audit(document_id=replacement["id"])
    superseded = [
        event for event in original_events if event["event_type"] == "document.superseded"
    ]
    replacement_issued = [
        event for event in replacement_events if event["event_type"] == "document.issued"
    ]
    assert len(superseded) == 1
    assert len(replacement_issued) == 1
    assert superseded[0]["event_data"] == expected_links
    assert replacement_issued[0]["event_data"] | expected_links == replacement_issued[0]["event_data"]


def test_final_revision_supersession_is_atomic_and_void_allows_recreate(repository, dsn):
    import psycopg

    created = project(repository)
    project_id = created["project"]["id"]
    issue_sales_order(repository, created, 1, "final-revision-sales-order-0001")
    final = invoice_with_total(
        repository, project_id, "FINAL", 1, "final-revision-final-0001"
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


def test_active_final_index_violation_maps_to_domain_conflict(repository):
    created = project(repository)
    issue_sales_order(repository, created, 1_000_000, "final-index-sales-order-0001")
    first = repository.create_invoice_draft(
        created["project"]["id"],
        values={"invoice_kind": "FINAL"},
        idempotency_key="final-index-first-create-0001",
        actor=ACTOR,
    )
    assert first["status"] == "draft"

    with pytest.raises(
        ProjectDocumentConflict,
        match="active FINAL invoice already exists",
    ):
        repository.create_invoice_draft(
            created["project"]["id"],
            values={"invoice_kind": "FINAL"},
            idempotency_key="final-index-second-create-0001",
            actor=ACTOR,
        )


def test_concurrent_final_revision_allows_only_one_pending_draft(repository, dsn):
    created = project(repository)
    issue_sales_order(repository, created, 1, "final-concurrent-sales-order-0001")
    final = invoice_with_total(
        repository,
        created["project"]["id"],
        "FINAL",
        1,
        "final-concurrent-final-0001",
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
    failures = [item for item in outcomes if isinstance(item, Exception)]
    assert len(failures) == 1
    assert isinstance(failures[0], ProjectDocumentConflict)
    assert "pending revision" in str(failures[0])


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


def test_schema_health_rejects_same_name_wrong_index_definition(repository, dsn):
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX uq_project_active_final_invoice")
            cursor.execute(
                "CREATE UNIQUE INDEX uq_project_active_final_invoice "
                "ON project_documents(id)"
            )
    status = project_document_schema_health(dsn)
    assert status["ready"] is False
    assert status["indexes"] is False


def test_schema_health_rejects_same_name_wrong_pending_revision_index(repository, dsn):
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX uq_project_pending_document_revision")
            cursor.execute(
                "CREATE UNIQUE INDEX uq_project_pending_document_revision "
                "ON project_documents(id)"
            )
    status = project_document_schema_health(dsn)
    assert status["ready"] is False
    assert status["indexes"] is False


def test_schema_health_rejects_malformed_core_column(repository, dsn):
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE projects ALTER COLUMN client_name DROP NOT NULL")
    status = project_document_schema_health(dsn)
    assert status["ready"] is False
    assert status["tables"] is False


def test_schema_health_rejects_same_name_wrong_constraint_definition(repository, dsn):
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE project_scopes "
                "DROP CONSTRAINT project_scopes_project_id_fkey"
            )
            cursor.execute(
                "ALTER TABLE project_scopes "
                "ADD CONSTRAINT project_scopes_project_id_fkey "
                "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
            )
    status = project_document_schema_health(dsn)
    assert status["ready"] is False
    assert status["constraints"] is False


def test_schema_health_rejects_same_name_wrong_trigger_definition(repository, dsn):
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER trg_projects_no_delete ON projects")
            cursor.execute(
                "CREATE TRIGGER trg_projects_no_delete AFTER DELETE ON projects "
                "FOR EACH ROW EXECUTE FUNCTION prevent_project_delete()"
            )
    status = project_document_schema_health(dsn)
    assert status["ready"] is False
    assert status["triggers"] is False


def test_schema_health_rejects_same_name_noop_guard_function(repository, dsn):
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION prevent_project_delete() RETURNS TRIGGER AS $$
                BEGIN
                    RETURN OLD;
                END;
                $$ LANGUAGE plpgsql
                """
            )
    status = project_document_schema_health(dsn)
    assert status["ready"] is False
    assert status["triggers"] is False


def test_invoice_payment_lifecycle_tracks_paid_outstanding_and_final_balance(repository):
    created = project(repository, key="payment-lifecycle-project-0001")
    project_id = created["project"]["id"]
    pre_contract = repository.get_project_payment_summary(project_id)
    assert pre_contract["payment_status"] == "NOT_CONTRACTED"
    assert pre_contract["contract_total"] is None
    assert pre_contract["contract_outstanding"] is None
    assert pre_contract["unbilled_total"] is None
    issue_sales_order(
        repository,
        created,
        total=1_000_000,
        key="payment-lifecycle-sales-order-0001",
    )
    dp = issue(
        repository,
        invoice_with_total(
            repository,
            project_id,
            "DP",
            400_000,
            "payment-lifecycle-dp-0001",
        ),
        "payment-lifecycle-dp-issue-0001",
    )

    first_source = insert_income(
        repository._dsn,
        project_id,
        amount=200_000,
        source_key="payment-lifecycle-ledger-0001",
    )
    first_receipt = ProjectDocumentService(repository).create_receipt(
        project_id,
        invoice_id=dp["id"],
        allocations=[{"ledger_source_key": first_source, "amount": 200_000}],
        values={"notes": "Pembayaran sebagian DP"},
        idempotency_key="payment-lifecycle-receipt-create-0001",
        actor=ACTOR,
    )
    before_issue = repository.get_project_payment_summary(project_id)
    assert before_issue["paid_total"] == 0
    assert before_issue["invoices"][0]["payment_status"] == "UNPAID"

    issued_first = issue(
        repository,
        first_receipt,
        "payment-lifecycle-receipt-issue-0001",
    )
    partial = repository.get_project_payment_summary(project_id)
    assert partial["contract_total"] == 1_000_000
    assert partial["invoiced_total"] == 400_000
    assert partial["unbilled_total"] == 600_000
    assert partial["paid_total"] == 200_000
    assert partial["contract_outstanding"] == 800_000
    assert partial["unapplied_total"] == 0
    assert partial["payment_status"] == "PARTIALLY_PAID"
    assert partial["invoices"][0] == {
        "invoice_id": dp["id"],
        "invoice_kind": "DP",
        "official_number": dp["official_number"],
        "due_date": dp["due_date"].isoformat() if hasattr(dp["due_date"], "isoformat") else dp["due_date"],
        "invoice_total": 400_000,
        "paid_total": 200_000,
        "outstanding": 200_000,
        "payment_status": "PARTIALLY_PAID",
    }
    assert repository.get_document(issued_first["id"])["applies_to_invoice_id"] == dp["id"]

    overpay_source = insert_income(
        repository._dsn,
        project_id,
        amount=250_000,
        source_key="payment-lifecycle-overpay-ledger-0001",
    )
    with pytest.raises(ProjectDocumentConflict, match="exceeds invoice outstanding"):
        ProjectDocumentService(repository).create_receipt(
            project_id,
            invoice_id=dp["id"],
            allocations=[{"ledger_source_key": overpay_source, "amount": 250_000}],
            values={},
            idempotency_key="payment-lifecycle-overpay-create-0001",
            actor=ACTOR,
        )

    second_source = insert_income(
        repository._dsn,
        project_id,
        amount=200_000,
        source_key="payment-lifecycle-ledger-0002",
    )
    second_receipt = ProjectDocumentService(repository).create_receipt(
        project_id,
        invoice_id=dp["id"],
        allocations=[{"ledger_source_key": second_source, "amount": 200_000}],
        values={},
        idempotency_key="payment-lifecycle-receipt-create-0002",
        actor=ACTOR,
    )
    issue(repository, second_receipt, "payment-lifecycle-receipt-issue-0002")
    dp_paid = repository.get_project_payment_summary(project_id)
    assert dp_paid["invoices"][0]["payment_status"] == "PAID"
    assert dp_paid["invoices"][0]["outstanding"] == 0

    final_invoice = issue(
        repository,
        invoice_with_total(
            repository,
            project_id,
            "FINAL",
            600_000,
            "payment-lifecycle-final-0001",
        ),
        "payment-lifecycle-final-issue-0001",
    )
    final_ready = repository.get_project_payment_summary(project_id)
    assert final_ready["invoiced_total"] == 1_000_000
    assert final_ready["unbilled_total"] == 0
    assert final_ready["contract_outstanding"] == 600_000
    assert [invoice["payment_status"] for invoice in final_ready["invoices"]] == [
        "PAID",
        "UNPAID",
    ]

    final_source = insert_income(
        repository._dsn,
        project_id,
        amount=600_000,
        source_key="payment-lifecycle-ledger-final-0001",
    )
    final_receipt = ProjectDocumentService(repository).create_receipt(
        project_id,
        invoice_id=final_invoice["id"],
        allocations=[{"ledger_source_key": final_source, "amount": 600_000}],
        values={"notes": "Pelunasan"},
        idempotency_key="payment-lifecycle-final-receipt-create-0001",
        actor=ACTOR,
    )
    issue(repository, final_receipt, "payment-lifecycle-final-receipt-issue-0001")

    paid = repository.get_project_payment_summary(project_id)
    assert paid["paid_total"] == 1_000_000
    assert paid["contract_outstanding"] == 0
    assert paid["overpaid_total"] == 0
    assert paid["payment_status"] == "PAID"
    assert all(invoice["payment_status"] == "PAID" for invoice in paid["invoices"])
    assert repository.get_project_payment_summary(project_id) == paid



def test_void_invoice_keeps_cash_and_marks_payment_unapplied(repository):
    created = project(repository, key="void-payment-project-0001")
    project_id = created["project"]["id"]
    issue_sales_order(repository, created, total=500_000, key="void-payment-sales-order-0001")
    invoice = issue(
        repository,
        invoice_with_total(repository, project_id, "DP", 250_000, "void-payment-dp-0001"),
        "void-payment-dp-issue-0001",
    )
    source_key = insert_income(
        repository._dsn,
        project_id,
        amount=100_000,
        source_key="void-payment-income-0001",
    )
    receipt_document = ProjectDocumentService(repository).create_receipt(
        project_id,
        invoice_id=invoice["id"],
        allocations=[{"ledger_source_key": source_key, "amount": 100_000}],
        values={},
        idempotency_key="void-payment-receipt-create-0001",
        actor=ACTOR,
    )
    issue(repository, receipt_document, "void-payment-receipt-issue-0001")
    repository.void_document(
        invoice["id"],
        reason="Tagihan dibatalkan",
        expected_version=invoice["lock_version"],
        idempotency_key="void-payment-invoice-void-0001",
        actor=ACTOR,
    )
    summary = repository.get_project_payment_summary(project_id)
    assert summary["invoiced_total"] == 0
    assert summary["paid_total"] == 100_000
    assert summary["unapplied_total"] == 100_000
    assert summary["contract_outstanding"] == 400_000
    assert summary["invoices"] == []



def test_void_receipt_releases_transaction_for_reallocation(repository):
    created = project(repository, key="void-receipt-candidate-project-0001")
    project_id = created["project"]["id"]
    source_key = insert_income(
        repository._dsn,
        project_id,
        amount=100_000,
        source_key="void-receipt-candidate-income-0001",
    )
    draft = ProjectDocumentService(repository).create_receipt(
        project_id,
        allocations=[{"ledger_source_key": source_key, "amount": 100_000}],
        values={},
        idempotency_key="void-receipt-candidate-create-0001",
        actor=ACTOR,
    )
    issued = issue(repository, draft, "void-receipt-candidate-issue-0001")
    assert repository.list_receipt_candidates(project_id) == []

    repository.void_document(
        issued["id"],
        reason="Pembayaran dibatalkan",
        expected_version=issued["lock_version"],
        idempotency_key="void-receipt-candidate-void-0001",
        actor=ACTOR,
    )
    candidates = repository.list_receipt_candidates(project_id)
    assert candidates[0]["source_key"] == source_key
    assert candidates[0]["available_amount"] == 100_000



def test_receipt_allocation_uses_canonical_project_id_not_legacy_label(repository, dsn):
    import psycopg

    first = project(repository, key="canonical-allocation-first-project-0001")["project"]
    second = project(repository, key="canonical-allocation-second-project-0001")["project"]
    source_key = insert_income(
        dsn,
        first["id"],
        source_key="canonical-allocation-cross-project-income-0001",
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE financial_ledger SET project_id = %s WHERE source_key = %s",
                (second["id"], source_key),
            )

    with pytest.raises(ProjectDocumentConflict, match="canonical project identity"):
        ProjectDocumentService(repository).create_receipt(
            first["id"],
            allocations=[{"ledger_source_key": source_key, "amount": 100_000}],
            values={},
            idempotency_key="canonical-allocation-cross-project-receipt-0001",
            actor=ACTOR,
        )


def test_receipt_allocation_accepts_project_name_label_when_canonical_id_matches(repository, dsn):
    import psycopg

    created = project(repository, key="canonical-allocation-name-project-0001")["project"]
    source_key = insert_income(
        dsn,
        created["id"],
        source_key="canonical-allocation-name-income-0001",
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE financial_ledger SET project = %s WHERE source_key = %s",
                (created["name"], source_key),
            )

    receipt_document = ProjectDocumentService(repository).create_receipt(
        created["id"],
        allocations=[{"ledger_source_key": source_key, "amount": 100_000}],
        values={},
        idempotency_key="canonical-allocation-name-receipt-0001",
        actor=ACTOR,
    )
    assert receipt_document["project_id"] == created["id"]


def test_schema_migration_repairs_malformed_canonical_project_fk(dsn):
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE financial_ledger DROP CONSTRAINT financial_ledger_project_id_fkey"
            )
            cursor.execute(
                "ALTER TABLE financial_ledger ADD CONSTRAINT financial_ledger_project_id_fkey "
                "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
            )

    assert project_document_schema_health(dsn)["ready"] is False
    assert ensure_project_document_schema(dsn)["ready"] is True
    assert project_document_schema_health(dsn)["ready"] is True
