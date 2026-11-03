import inspect
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from services.project_document_repository import (
    ProjectDocumentRepository,
    ProjectDocumentUnavailable,
    canonical_json_hash,
    format_official_number,
)


ROOT = Path(__file__).parents[1]


def test_migration_defines_exact_schema_and_database_guards():
    sql = (ROOT / "dashboard_api/migrations/003_project_documents.sql").read_text(encoding="utf-8")

    for table in (
        "project_issuer_profiles",
        "projects",
        "project_scopes",
        "project_documents",
        "project_document_lines",
        "project_document_allocations",
        "project_document_number_counters",
        "project_document_events",
        "project_document_artifacts",
        "project_document_commands",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    for required in (
        "uq_project_issuer_profiles_number_code",
        "uq_project_active_final_invoice",
        "prevent_project_delete",
        "prevent_project_document_delete",
        "prevent_project_document_mutation",
        "prevent_non_draft_document_child_mutation",
        "prevent_project_document_event_mutation",
        "prevent_project_document_artifact_mutation",
    ):
        assert required in sql
    assert "ON DELETE CASCADE" not in sql
    assert "financial_ledger" in sql
    assert "FOR UPDATE" in sql
    assert "sales_order" in sql and "invoice" in sql and "receipt" in sql
    assert "quotation" not in sql
    assert "credit_note" not in sql


def test_issue_interface_only_accepts_server_renderer_output():
    signature = inspect.signature(ProjectDocumentRepository.issue_document)

    assert "snapshot" not in signature.parameters
    assert "pdf_bytes" not in signature.parameters
    assert "renderer_version" not in signature.parameters
    assert "renderer" in inspect.signature(ProjectDocumentRepository).parameters


def test_number_format_uses_jakarta_calendar_year_and_type_prefixes():
    instant = datetime(2026, 12, 31, 17, 30, tzinfo=ZoneInfo("UTC"))

    assert format_official_number("sales_order", "HW", 7, instant) == "SO/HW/2027/000007"
    assert format_official_number("invoice", "HW", 12, instant) == "INV/HW/2027/000012"
    assert format_official_number("receipt", "HW", 1, instant) == "KWT/HW/2027/000001"
    with pytest.raises(ValueError, match="unsupported document type"):
        format_official_number("quotation", "HW", 1, instant)


def test_canonical_json_hash_is_order_independent_and_rejects_non_json_values():
    first = canonical_json_hash({"b": [2, 1], "a": "Holla"})
    second = canonical_json_hash({"a": "Holla", "b": [2, 1]})

    assert first == second
    assert len(first) == 64
    with pytest.raises(TypeError, match="JSON"):
        canonical_json_hash({"bad": object()})


def test_repository_fails_closed_without_postgres_configuration(monkeypatch):
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    repository = ProjectDocumentRepository()

    with pytest.raises(ProjectDocumentUnavailable, match="requires STATE_DATABASE_URL or DATABASE_URL"):
        repository.list_projects()


def test_schema_health_is_read_only_and_requires_exact_catalog_objects(monkeypatch):
    import services.project_document_repository as module

    executed = []

    class Cursor:
        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))

        def fetchone(self):
            return (True, True, True, True)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(module, "_default_connection_factory", lambda _dsn: Connection())

    status = module.project_document_schema_health("postgresql://isolated-test")

    assert status == {
        "ready": True,
        "tables": True,
        "constraints": True,
        "indexes": True,
        "triggers": True,
    }
    health_sql = executed[0]
    for exact_object in (
        "uq_project_issuer_profiles_number_code",
        "uq_project_active_final_invoice",
        "trg_projects_no_delete",
        "trg_project_documents_no_delete",
        "trg_project_document_immutable",
        "trg_project_document_events_append_only",
    ):
        assert exact_object in health_sql
    assert all("CREATE TABLE" not in statement for statement in executed)
