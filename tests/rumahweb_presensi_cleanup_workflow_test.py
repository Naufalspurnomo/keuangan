from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rumahweb-presensi-cleanup.yml"


def test_presensi_cleanup_workflow_is_manual_bounded_and_owner_scoped() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    trigger = workflow.get("on") or workflow.get(True)

    assert set(trigger) == {"workflow_dispatch"}
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert inputs["event_ids"]["required"] is True
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["jobs"]["cleanup"]["timeout-minutes"] == 8
    assert "secrets.RUMAHWEB_FTP_HOST" in text
    assert "secrets.RUMAHWEB_FTP_USER" in text
    assert "secrets.RUMAHWEB_FTP_PASSWORD" in text
    assert "--event-ids \"$EVENT_IDS\"" in text
    assert "readback_clean" in text
    assert "credentials_exposed" in text
    assert "actions/upload-artifact" in text
