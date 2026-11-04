from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_validate_rejects_missing_required_fields(monkeypatch, tmp_path, capsys):
    from scripts import seed_project_document_issuer

    config = tmp_path / "issuer.json"
    config.write_text(json.dumps({"issuer_key": "hollawall"}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["seed_project_document_issuer.py", "--file", str(config)])
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as error:
        seed_project_document_issuer.main()

    assert error.value.code == 2
    body = json.loads(capsys.readouterr().out)
    assert body["action"] == "validate"
    assert body["error"] == "invalid_issuer_file"
    assert "legal_name" in body["missing"]


def test_validate_is_default_and_does_not_access_database(monkeypatch, tmp_path, capsys):
    from scripts import seed_project_document_issuer

    config = tmp_path / "issuer.json"
    config.write_text(json.dumps({
        "issuer_key": "hollawall",
        "legal_name": "CV Example",
        "display_name": "Example",
        "number_code": "EX",
        "address": "Address",
        "expected_version": 0,
        "bank_details": {},
    }), encoding="utf-8")
    monkeypatch.setattr(seed_project_document_issuer, "ProjectDocumentRepository", lambda *_a, **_k: pytest.fail("validate must not open DB"))
    monkeypatch.setattr(sys, "argv", ["seed_project_document_issuer.py", "--file", str(config)])

    seed_project_document_issuer.main()

    body = json.loads(capsys.readouterr().out)
    assert body == {
        "action": "validate",
        "issuer_key": "hollawall",
        "number_code": "EX",
        "valid": True,
    }


def test_apply_requires_database_and_explicit_confirmation(monkeypatch, tmp_path, capsys):
    from scripts import seed_project_document_issuer

    config = tmp_path / "issuer.json"
    config.write_text(json.dumps({
        "issuer_key": "hollawall",
        "legal_name": "CV Example",
        "display_name": "Example",
        "number_code": "EX",
        "address": "Address",
        "expected_version": 0,
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["seed_project_document_issuer.py", "--file", str(config), "--apply"])
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://redacted")

    with pytest.raises(SystemExit) as error:
        seed_project_document_issuer.main()

    assert error.value.code == 2
    body = json.loads(capsys.readouterr().out)
    assert body["error"] == "confirmation_required"
    assert "postgresql://" not in json.dumps(body)


def test_apply_calls_idempotent_repository_without_printing_sensitive_fields(monkeypatch, tmp_path, capsys):
    from scripts import seed_project_document_issuer

    config = tmp_path / "issuer.json"
    config.write_text(json.dumps({
        "issuer_key": "hollawall",
        "legal_name": "CV Example",
        "display_name": "Example",
        "number_code": "EX",
        "address": "Private Address",
        "phone": "private-phone",
        "email": "private@example.com",
        "expected_version": 0,
        "bank_details": {"account": "private-account"},
    }), encoding="utf-8")
    calls = []

    class Repository:
        def __init__(self, dsn):
            calls.append(("dsn", dsn))

        def upsert_issuer_profile(self, **kwargs):
            calls.append(("upsert", kwargs))
            return {
                "issuer_key": kwargs["issuer_key"],
                "number_code": kwargs["number_code"],
                "profile_version": 1,
            }

    monkeypatch.setattr(seed_project_document_issuer, "ProjectDocumentRepository", Repository)
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "seed_project_document_issuer.py",
        "--file", str(config),
        "--apply",
        "--confirm", "APPLY_ISSUER_PROFILE",
    ])

    seed_project_document_issuer.main()

    body_text = capsys.readouterr().out
    body = json.loads(body_text)
    assert body == {
        "action": "apply",
        "issuer_key": "hollawall",
        "number_code": "EX",
        "profile_version": 1,
    }
    assert "private" not in body_text
    assert calls[1][1]["idempotency_key"].startswith("issuer-bootstrap-")
