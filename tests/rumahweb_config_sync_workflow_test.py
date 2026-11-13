from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rumahweb-config-sync.yml"


def test_private_config_sync_is_manual_bounded_and_does_not_deploy_site() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "timeout-minutes: 8" in text
    assert "configure_rumahweb_admin_finance.py" in text
    assert "snapshot_url_configured" in text
    assert "deploy_rumahweb_presensi_atomic.py" not in text
    assert "npm ci" not in text
    for secret in (
        "secrets.RUMAHWEB_FTP_HOST",
        "secrets.RUMAHWEB_FTP_USER",
        "secrets.RUMAHWEB_FTP_PASSWORD",
        "secrets.HOLLAWALL_DASHBOARD_ACTOR_ASSERTION_SECRET",
    ):
        assert secret in text
