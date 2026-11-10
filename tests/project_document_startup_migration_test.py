"""Startup migration gate for the project/document schema."""

from __future__ import annotations

import main


def test_project_document_startup_migration_skips_when_writes_are_disabled(monkeypatch):
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://configured")
    monkeypatch.setenv("PROJECT_DOCUMENT_WRITES_ENABLED", "0")
    monkeypatch.setattr(
        main,
        "ensure_project_document_schema",
        lambda _dsn: (_ for _ in ()).throw(AssertionError("DDL must stay disabled")),
        raising=False,
    )

    assert main.migrate_project_document_schema_at_startup() == {
        "configured": True,
        "writes_enabled": False,
        "ready": False,
        "skipped": True,
    }


def test_project_document_startup_migration_runs_once_when_writes_are_enabled(monkeypatch):
    calls: list[str] = []
    expected = {
        "ready": True,
        "tables": True,
        "constraints": True,
        "indexes": True,
        "triggers": True,
    }
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://configured")
    monkeypatch.setenv("PROJECT_DOCUMENT_WRITES_ENABLED", "1")
    monkeypatch.setattr(
        main,
        "ensure_project_document_schema",
        lambda dsn: calls.append(dsn) or expected,
        raising=False,
    )

    assert main.migrate_project_document_schema_at_startup() == {
        "configured": True,
        "writes_enabled": True,
        **expected,
    }
    assert calls == ["postgresql://configured"]


def test_project_document_startup_migration_fails_closed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.setenv("PROJECT_DOCUMENT_WRITES_ENABLED", "true")
    monkeypatch.setattr(
        main,
        "ensure_project_document_schema",
        lambda _dsn: (_ for _ in ()).throw(main.ProjectDocumentUnavailable("unavailable")),
        raising=False,
    )

    status = main.migrate_project_document_schema_at_startup()

    assert status["configured"] is True
    assert status["writes_enabled"] is True
    assert status["ready"] is False
    assert status["error"] == "ProjectDocumentUnavailable"
