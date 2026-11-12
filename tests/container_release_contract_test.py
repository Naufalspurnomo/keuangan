from pathlib import Path
from unittest.mock import patch

from scripts import activate_canonical_finance


ROOT = Path(__file__).resolve().parents[1]


def test_container_healthcheck_fails_on_http_error_and_wrong_contract():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "raise_for_status()" in dockerfile
    assert "payload.get('status')" in dockerfile


def test_production_image_activates_fresh_zero_postgres_before_gunicorn():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    activation = (ROOT / "scripts" / "activate_canonical_finance.py").read_text(
        encoding="utf-8"
    )

    for flag in (
        "CANONICAL_FINANCE_API_ENABLED=1",
        "CANONICAL_FINANCE_READS_ENABLED=1",
        "CANONICAL_FINANCE_WRITES_ENABLED=1",
        "CANONICAL_FINANCE_LATCH_ENFORCED=1",
        "PROJECT_DOCUMENT_WRITES_ENABLED=1",
    ):
        assert flag in dockerfile
    command = next(line for line in dockerfile.splitlines() if line.startswith("CMD ["))
    assert "python -m scripts.activate_canonical_finance" in command
    assert command.index("python -m scripts.activate_canonical_finance") < command.index("gunicorn")
    assert "load_production_bootstrap_migrations" in activation
    assert "LOCK TABLE" in activation
    assert "historical_import" in activation
    assert "canonical finance activation requires fresh-zero business tables" in activation
    assert "_PROJECT_TABLES + _FINANCE_TABLES" in activation
    assert "for table in _FINANCE_TABLES" in activation


def test_container_gate_provides_postgres_to_canonical_activation():
    workflow = (ROOT / ".github" / "workflows" / "production-gate.yml").read_text(
        encoding="utf-8"
    )
    container = workflow.split("\n  container:\n", 1)[1].split("\n  performance:\n", 1)[0]
    assert "image: postgres:16-alpine" in container
    assert "--network host" in container
    assert "DATABASE_URL=postgresql://hollawall_test:ci_test_only@127.0.0.1:5432/hollawall_test" in container
    assert "http://127.0.0.1:8000/health" in container
    assert "STATE_STORE_BACKEND=local" in container
    assert "PROJECT_DOCUMENT_WRITES_ENABLED=0" not in container
    assert "project_document_schema" in container
    assert '"tables", "constraints", "indexes", "triggers"' in container
    assert "seed_project_document_issuer.py" in container
    assert "APPLY_ISSUER_PROFILE" in container
    assert container.index('"tables", "constraints", "indexes", "triggers"') < container.index("seed_project_document_issuer.py")


def test_production_container_without_database_fails_closed_even_in_local_mode():
    with (
        patch.dict(
            "os.environ",
            {
                "CANONICAL_FINANCE_ACTIVATE": "1",
                "STATE_STORE_BACKEND": "local",
            },
            clear=True,
        ),
        patch.object(activate_canonical_finance, "apply_financial_migrations") as migrate,
    ):
        try:
            activate_canonical_finance.activate()
        except RuntimeError as error:
            assert str(error) == "canonical finance activation requires a database DSN"
        else:
            raise AssertionError("production activation must fail closed without a database DSN")

    migrate.assert_not_called()


def test_nonlocal_container_without_database_fails_closed():
    with patch.dict(
        "os.environ",
        {"CANONICAL_FINANCE_ACTIVATE": "1", "STATE_STORE_BACKEND": "postgresql"},
        clear=True,
    ):
        try:
            activate_canonical_finance.activate()
        except RuntimeError as error:
            assert str(error) == "canonical finance activation requires a database DSN"
        else:
            raise AssertionError("production activation must fail closed without a database DSN")


def test_container_context_excludes_private_runtime_material():
    patterns = {
        line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required = {
        ".env.*", ".hermes", "artifacts", "data", "runtime", "tmp",
        "*.xlsx", "token.json", "credentials.json", "client_secret*.json",
    }
    assert required <= patterns
