from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_inbox_review.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("STATE_DATABASE_URL", None)
    env.pop("DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=ROOT, env=env,
        text=True, capture_output=True, check=False,
    )


def test_check_is_default_and_fails_closed_without_database():
    result = run_cli()
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "action": "check", "configured": False,
        "error": "database_not_configured", "ready": False,
    }
    assert result.stderr == ""


def test_apply_requires_literal_confirmation(monkeypatch, capsys):
    from scripts import migrate_inbox_review

    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://redacted")
    monkeypatch.setattr(sys, "argv", ["migrate_inbox_review.py", "--apply"])
    with pytest.raises(SystemExit) as captured:
        migrate_inbox_review.main()
    assert captured.value.code == 2
    body = json.loads(capsys.readouterr().out)
    assert body["error"] == "confirmation_required"
    assert "postgresql://" not in json.dumps(body)


def test_apply_executes_migration_then_requires_health_readback(monkeypatch, capsys):
    from scripts import migrate_inbox_review

    calls: list[str] = []
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://redacted")
    monkeypatch.setattr(migrate_inbox_review, "apply_migration", lambda dsn: calls.append(dsn))
    monkeypatch.setattr(
        migrate_inbox_review, "schema_health",
        lambda dsn: {"configured": True, "ready": True, "audit_ready": True},
    )
    monkeypatch.setattr(sys, "argv", [
        "migrate_inbox_review.py", "--apply", "--confirm", "APPLY_INBOX_REVIEW_SCHEMA",
    ])

    migrate_inbox_review.main()

    assert calls == ["postgresql://redacted"]
    body = json.loads(capsys.readouterr().out)
    assert body["action"] == "apply"
    assert body["ready"] is True
    assert "postgresql://" not in json.dumps(body)
