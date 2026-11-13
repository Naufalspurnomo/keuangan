from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rumahweb-deploy.yml"
DEPLOYER = ROOT / "scripts" / "deploy_rumahweb_presensi_atomic.py"


def test_rumahweb_deploy_runs_only_after_green_main_gate_or_manual_dispatch():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'workflows: ["Production Gate"]' in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "Require exact main revision" in text
    assert "fetch-depth: 2" in text
    assert "git rev-parse origin/main" in text
    assert "GITHUB_TOKEN: ${{ github.token }}" in text
    assert "api.github.com/repos/" in text
    assert "parents[0]['sha']" in text
    assert "rev-parse', 'HEAD^'" not in text


def test_rumahweb_deploy_uses_scoped_secrets_and_atomic_readback():
    text = WORKFLOW.read_text(encoding="utf-8")

    for secret in (
        "secrets.RUMAHWEB_FTP_HOST",
        "secrets.RUMAHWEB_FTP_USER",
        "secrets.RUMAHWEB_FTP_PASSWORD",
    ):
        assert secret in text
    assert "deploy_rumahweb_presensi_atomic.py" in text
    assert "--admin-remote public_html/admin" in text
    assert "--absen-remote public_html/absen" in text
    assert "release-manifest.json?sha=${RELEASE_SHA}" in text
    assert "release.json?sha=${RELEASE_SHA}" not in text
    assert "staged_readback" in text
    assert "final_readback" in text
    assert "concurrency:" in text
    assert "workflow_dispatch" in text
    assert "OTP" not in text


def test_deployer_supports_non_mutating_credential_probe():
    text = DEPLOYER.read_text(encoding="utf-8")

    assert '"--probe-only"' in text
    assert '"remote_mutated": False' in text
