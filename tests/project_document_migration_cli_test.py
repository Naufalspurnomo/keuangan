from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_project_documents.py"


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    selected = os.environ.copy()
    selected.pop("STATE_DATABASE_URL", None)
    selected.pop("DATABASE_URL", None)
    if env:
        selected.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=selected,
        text=True,
        capture_output=True,
        check=False,
    )


def test_check_is_default_and_fails_closed_without_dsn():
    result = run_cli()

    assert result.returncode == 2
    body = json.loads(result.stdout)
    assert body == {
        "action": "check",
        "configured": False,
        "error": "database_not_configured",
        "ready": False,
    }
    assert result.stderr == ""


def test_apply_requires_explicit_confirmation(monkeypatch, capsys):
    from scripts import migrate_project_documents

    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://redacted")
    monkeypatch.setattr(
        sys,
        "argv",
        ["migrate_project_documents.py", "--apply"],
    )

    with pytest.raises(SystemExit) as error:
        migrate_project_documents.main()

    assert error.value.code == 2
    body = json.loads(capsys.readouterr().out)
    assert body["action"] == "apply"
    assert body["error"] == "confirmation_required"
    assert "postgresql://" not in json.dumps(body)


def test_check_reports_exact_schema_health_without_mutation(monkeypatch, capsys):
    from scripts import migrate_project_documents

    expected = {
        "ready": True,
        "tables": True,
        "constraints": True,
        "indexes": True,
        "triggers": True,
    }
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.setattr(migrate_project_documents, "project_document_schema_health", lambda _dsn: expected)
    monkeypatch.setattr(
        migrate_project_documents,
        "ensure_project_document_schema",
        lambda _dsn: pytest.fail("check mode must not execute DDL"),
    )
    monkeypatch.setattr(sys, "argv", ["migrate_project_documents.py"])

    migrate_project_documents.main()

    body = json.loads(capsys.readouterr().out)
    assert body == {"action": "check", "configured": True, **expected}
    assert "postgresql://" not in json.dumps(body)


def test_apply_runs_once_and_requires_complete_readback(monkeypatch, capsys):
    from scripts import migrate_project_documents

    calls: list[str] = []
    healthy = {
        "ready": True,
        "tables": True,
        "constraints": True,
        "indexes": True,
        "triggers": True,
    }
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://redacted")
    monkeypatch.setattr(
        migrate_project_documents,
        "ensure_project_document_schema",
        lambda dsn: calls.append(dsn) or healthy,
    )
    monkeypatch.setattr(sys, "argv", [
        "migrate_project_documents.py",
        "--apply",
        "--confirm",
        "APPLY_PROJECT_DOCUMENT_SCHEMA",
    ])

    migrate_project_documents.main()

    assert calls == ["postgresql://redacted"]
    body = json.loads(capsys.readouterr().out)
    assert body == {"action": "apply", "configured": True, **healthy}
    assert "postgresql://" not in json.dumps(body)


def test_apply_exits_nonzero_when_readback_is_incomplete(monkeypatch, capsys):
    from scripts import migrate_project_documents

    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://redacted")
    monkeypatch.setattr(
        migrate_project_documents,
        "ensure_project_document_schema",
        lambda _dsn: {
            "ready": False,
            "tables": True,
            "constraints": True,
            "indexes": False,
            "triggers": True,
        },
    )
    monkeypatch.setattr(sys, "argv", [
        "migrate_project_documents.py",
        "--apply",
        "--confirm",
        "APPLY_PROJECT_DOCUMENT_SCHEMA",
    ])

    with pytest.raises(SystemExit) as error:
        migrate_project_documents.main()

    assert error.value.code == 1
    body = json.loads(capsys.readouterr().out)
    assert body["ready"] is False
    assert body["indexes"] is False
