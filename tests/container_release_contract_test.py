from pathlib import Path


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
    assert "scripts/activate_canonical_finance.py" in dockerfile
    assert dockerfile.index("scripts/activate_canonical_finance.py") < dockerfile.index("gunicorn")
    assert "load_production_bootstrap_migrations" in activation
    assert "LOCK TABLE" in activation
    assert "historical_import" in activation
    assert "canonical finance activation requires fresh-zero business tables" in activation


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
