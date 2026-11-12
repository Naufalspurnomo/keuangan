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


def test_local_container_without_database_skips_production_activation():
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
        activate_canonical_finance.activate()

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
