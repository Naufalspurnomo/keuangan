from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_container_healthcheck_fails_on_http_error_and_wrong_contract():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "raise_for_status()" in dockerfile
    assert "payload.get('status')" in dockerfile


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
