from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts import monitoring_contract
from scripts import promotion_guard


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "production-gate.yml"
MONITORING = ROOT / "release" / "monitoring.v1.json"
EXPECTED_SIGNALS = {
    "inbox",
    "export",
    "error",
    "api",
    "backup",
    "review",
    "wuzapi",
    "presensi",
}


def test_production_gate_job_ids_are_the_promotion_contract() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert set(workflow["jobs"]) == set(promotion_guard.REQUIRED_CHECKS)
    for check in promotion_guard.REQUIRED_CHECKS:
        job = workflow["jobs"][check]
        assert job["runs-on"]
        assert job["steps"]
        assert any("run" in step or "uses" in step for step in job["steps"])


def test_backend_job_installs_yaml_for_release_contract_collection() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    install = "\n".join(
        str(step.get("run", "")) for step in workflow["jobs"]["backend"]["steps"]
    )
    assert "PyYAML==6.0.3" in install


def test_history_dependent_jobs_fetch_candidate_ancestry() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    for job_id in ("backend", "accessibility"):
        checkout = next(
            step for step in workflow["jobs"][job_id]["steps"]
            if str(step.get("uses", "")).startswith("actions/checkout@")
        )
        assert checkout.get("with", {}).get("fetch-depth") == "0"


def test_backup_cli_wires_the_selected_psql_command(monkeypatch, capsys) -> None:
    from scripts import hollawall_backup

    captured = {}

    def fake_run(config, *, apply):
        captured["config"] = config
        captured["apply"] = apply
        return {"action": "dry-run"}

    monkeypatch.setattr(hollawall_backup, "run_backup", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "hollawall_backup.py",
            "--output-dir", "/tmp/out",
            "--sheets-source", "/tmp/sheets",
            "--presensi-source", "/tmp/presensi",
            "--psql-command", "custom-psql",
        ],
    )
    hollawall_backup.main()
    capsys.readouterr()

    assert captured["config"].psql_command == "custom-psql"
    assert captured["apply"] is False


def test_numeric_monitoring_contract_covers_every_release_signal() -> None:
    contract = monitoring_contract.load_contract(MONITORING)

    assert contract["schema"] == "hollawall.monitoring/v1"
    assert set(contract["signals"]) == EXPECTED_SIGNALS
    for name, signal in contract["signals"].items():
        assert signal["metric"]
        assert signal["unit"] in {"count", "ratio", "seconds", "milliseconds"}
        assert type(signal["window_seconds"]) is int
        assert signal["window_seconds"] > 0
        assert type(signal["warning"]) in {int, float}
        assert type(signal["critical"]) in {int, float}
        assert signal["warning"] < signal["critical"], name


@pytest.mark.parametrize("signal", sorted(EXPECTED_SIGNALS))
def test_synthetic_critical_alerts_fire_for_every_signal(signal: str) -> None:
    contract = monitoring_contract.load_contract(MONITORING)
    threshold = contract["signals"][signal]["critical"]

    alert = monitoring_contract.evaluate(contract, signal, threshold)

    assert alert == {
        "schema": "hollawall.monitoring-alert/v1",
        "signal": signal,
        "severity": "critical",
        "value": threshold,
        "threshold": threshold,
        "window_seconds": contract["signals"][signal]["window_seconds"],
    }


def test_synthetic_alert_boundaries_are_numeric_and_fail_closed(tmp_path: Path) -> None:
    contract = monitoring_contract.load_contract(MONITORING)
    api = contract["signals"]["api"]

    assert monitoring_contract.evaluate(contract, "api", api["warning"] - 1)["severity"] == "ok"
    assert monitoring_contract.evaluate(contract, "api", api["warning"])["severity"] == "warning"
    assert monitoring_contract.evaluate(contract, "api", api["critical"])["severity"] == "critical"
    with pytest.raises(monitoring_contract.MonitoringContractError, match="finite number"):
        monitoring_contract.evaluate(contract, "api", float("nan"))

    invalid = json.loads(MONITORING.read_text(encoding="utf-8"))
    invalid["signals"]["backup"]["critical"] = "one day"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(monitoring_contract.MonitoringContractError, match="numeric"):
        monitoring_contract.load_contract(path)
