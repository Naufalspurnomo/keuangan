"""Non-mutating release gate regression coverage."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('finance_preflight', ROOT / 'scripts/configure_rumahweb_admin_finance.py')
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SHA = 'a' * 40


def test_preflight_rejects_non_exact_sha_before_network():
    with pytest.raises(RuntimeError, match='40-character'):
        module.preflight_backend('https://backend.test/api/dashboard/v1/canonical-transactions', 'https://backend.test/api/dashboard/v1/snapshot', 'short', 'token')


def replies(monkeypatch, *, sha=SHA, schema=True, status=422, code="invalid_json"):
    calls = []
    def probe(url, token, *, method="GET"):
        calls.append((url, method))
        if url.endswith("/api/health/release"):
            return 200, {"release_sha": sha}
        if url.endswith("/snapshot"):
            return 200, {"data": {}}
        if url.endswith("/health"):
            return 200, {"dashboard_write_schema": {"ready": schema}, "project_document_schema": {"ready": True}}
        return status, {"error": {"code": code}}
    monkeypatch.setattr(module, "probe_json", probe)
    return calls


def run():
    return module.preflight_backend("https://backend.test/api/dashboard/v1/canonical-transactions", "https://backend.test/api/dashboard/v1/snapshot", SHA, "token")


def test_accepts_only_ready_backend_and_checks_all_mutation_routes(monkeypatch):
    calls = replies(monkeypatch)
    assert run()["ok"] is True
    assert len(calls) == 7
    assert [method for _, method in calls] == ["GET", "GET", "GET", "POST", "POST", "POST", "GET"]


@pytest.mark.parametrize("change", [{"sha": "b" * 40}, {"schema": False}, {"schema": "true"}, {"status": 404}, {"status": 401}, {"status": 503}, {"status": 200}, {"code": "canonical_writes_disabled"}, {"code": "canonical_authority_unavailable"}])
def test_blocks_incompatible_backend(monkeypatch, change):
    replies(monkeypatch, **change)
    with pytest.raises(RuntimeError):
        run()


def test_blocks_release_change_during_preflight(monkeypatch):
    calls = replies(monkeypatch)
    original = module.probe_json
    def probe(*args, **kwargs):
        result = original(*args, **kwargs)
        return (200, {"release_sha": "b" * 40}) if len(calls) == 7 else result
    monkeypatch.setattr(module, "probe_json", probe)
    with pytest.raises(RuntimeError, match="SHA mismatch"):
        run()


@pytest.mark.parametrize("url", ["http://backend.test/api/dashboard/v1/snapshot", "https://other.test/api/dashboard/v1/snapshot", "https://user:pass@backend.test/api/dashboard/v1/snapshot", "https://backend.test/api/dashboard/v1/snapshot?x=1"])
def test_rejects_unsafe_or_mixed_origins(url):
    with pytest.raises(RuntimeError):
        module.preflight_backend("https://backend.test/api/dashboard/v1/canonical-transactions", url, SHA, "token")


def test_invalid_json_probe_cannot_reach_finance_service():
    from flask import Flask
    from dashboard_api.canonical_finance_routes import create_canonical_finance_blueprint
    class ForbiddenService:
        def __getattr__(self, name):
            raise AssertionError("preflight must never call finance service")
    app = Flask(__name__)
    app.config["CANONICAL_FINANCE_WRITES_ENABLED"] = True
    app.extensions["canonical_finance_write_authority"] = lambda: "postgresql"
    app.register_blueprint(create_canonical_finance_blueprint(ForbiddenService()))
    for suffix in ("", "/__release_preflight__/corrections", "/__release_preflight__/reversals"):
        response = app.test_client().post("/api/dashboard/v1/canonical-transactions" + suffix, data=b"{", content_type="application/json")
        assert response.status_code == 422
        assert response.json is not None
        assert response.json["error"]["code"] == "invalid_json"


def test_workflow_gates_before_remote_deploy():
    text = (ROOT / ".github/workflows/rumahweb-deploy.yml").read_text()
    assert text.index("--preflight-only") < text.index("python scripts/deploy_rumahweb_presensi_atomic.py")
    sync = text.split("- name: Synchronize private finance routing", 1)[1]
    assert "RELEASE_SHA: ${{ steps.revision.outputs.sha }}" in sync
