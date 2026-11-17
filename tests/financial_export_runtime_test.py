from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import financial_export_runtime as runtime


ROOT = Path(__file__).resolve().parents[1]


class FakeWorksheet:
    title = "_CANONICAL_FINANCE_EXPORT"
    id = 123


class FakeSpreadsheet:
    id = "sheet-workbook-123"

    def worksheet(self, title: str):
        assert title == FakeWorksheet.title
        return FakeWorksheet()

    def fetch_sheet_metadata(self, *, params):
        assert "protectedRanges" in params["fields"]
        return {
            "sheets": [
                {
                    "properties": {"sheetId": FakeWorksheet.id},
                    "protectedRanges": [
                        {
                            "range": {
                                "sheetId": FakeWorksheet.id,
                                "startColumnIndex": 0,
                                "endColumnIndex": 10,
                            }
                        }
                    ],
                }
            ]
        }


class FakeOutbox:
    def __init__(self, dsn: str):
        self.dsn = dsn


class FakeRemote:
    def __init__(self, worksheet, *, expected_workbook_id: str, expected_title: str, ensure_header: bool):
        self.worksheet = worksheet
        self.expected_workbook_id = expected_workbook_id
        self.expected_title = expected_title
        self.ensure_header = ensure_header


class FakeWorker:
    def __init__(self, *, outbox, remote, protected_destination: bool, lease_seconds: int):
        self.outbox = outbox
        self.remote = remote
        self.protected_destination = protected_destination
        self.lease_seconds = lease_seconds
        self.calls = []

    def run_once(self, *, limit: int):
        self.calls.append(limit)
        return {"claimed": 1, "exported": 1}


def test_build_worker_binds_external_postgres_and_protected_sheets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://external.example/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fallback.example/db")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-workbook-123")
    monkeypatch.setenv("FINANCIAL_EXPORT_WORKSHEET", FakeWorksheet.title)
    monkeypatch.setenv("FINANCIAL_EXPORT_PROTECTED_DESTINATION", "true")
    monkeypatch.setenv("FINANCIAL_EXPORT_LEASE_SECONDS", "77")
    monkeypatch.setattr(runtime, "get_spreadsheet", lambda: FakeSpreadsheet())
    monkeypatch.setattr(runtime, "PostgresExportOutbox", FakeOutbox)
    monkeypatch.setattr(runtime, "GoogleSheetsRemoteExport", FakeRemote)
    monkeypatch.setattr(runtime, "ExportWorker", FakeWorker)

    worker = runtime.build_export_worker()

    assert worker.outbox.dsn == "postgresql://external.example/db"
    assert worker.remote.expected_workbook_id == "sheet-workbook-123"
    assert worker.remote.expected_title == FakeWorksheet.title
    assert worker.remote.ensure_header is True
    assert worker.protected_destination is True
    assert worker.lease_seconds == 77


def test_build_worker_falls_back_to_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STATE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fallback.example/db")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-workbook-123")
    monkeypatch.setenv("FINANCIAL_EXPORT_WORKSHEET", FakeWorksheet.title)
    monkeypatch.setenv("FINANCIAL_EXPORT_PROTECTED_DESTINATION", "true")
    monkeypatch.setattr(runtime, "get_spreadsheet", lambda: FakeSpreadsheet())
    monkeypatch.setattr(runtime, "PostgresExportOutbox", FakeOutbox)
    monkeypatch.setattr(runtime, "GoogleSheetsRemoteExport", FakeRemote)
    monkeypatch.setattr(runtime, "ExportWorker", FakeWorker)

    worker = runtime.build_export_worker()

    assert worker.outbox.dsn == "postgresql://fallback.example/db"


def test_build_worker_fails_closed_when_export_is_not_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://external.example/db")
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://wrong-state.example/db")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-workbook-123")
    monkeypatch.setenv("FINANCIAL_EXPORT_PROTECTED_DESTINATION", "false")

    with pytest.raises(RuntimeError, match="protected destination"):
        runtime.build_export_worker()


def test_build_worker_fails_closed_when_sheet_has_no_protected_range(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnprotectedSpreadsheet(FakeSpreadsheet):
        def fetch_sheet_metadata(self, *, params):
            return {"sheets": [{"properties": {"sheetId": FakeWorksheet.id}}]}

    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://external.example/db")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-workbook-123")
    monkeypatch.setenv("FINANCIAL_EXPORT_WORKSHEET", FakeWorksheet.title)
    monkeypatch.delenv("FINANCIAL_EXPORT_PROTECTED_DESTINATION", raising=False)
    monkeypatch.setattr(runtime, "get_spreadsheet", lambda: UnprotectedSpreadsheet())

    with pytest.raises(RuntimeError, match="destination is not protected"):
        runtime.build_export_worker()


def test_export_defaults_on_only_for_fully_configured_koyeb(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "FINANCIAL_EXPORT_ENABLED",
        "KOYEB_SERVICE_ID",
        "STATE_DATABASE_URL",
        "DATABASE_URL",
        "GOOGLE_SHEETS_ID",
        "GOOGLE_CREDENTIALS",
    ):
        monkeypatch.delenv(key, raising=False)
    assert runtime._export_enabled() is False

    monkeypatch.setenv("KOYEB_SERVICE_ID", "service-123")
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://external.example/db")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-workbook-123")
    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"private_key":"secret"}')
    assert runtime._export_enabled() is True

    monkeypatch.setenv("FINANCIAL_EXPORT_ENABLED", "false")
    assert runtime._export_enabled() is False


def test_export_loop_is_stop_event_driven_and_runs_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()
    worker = SimpleNamespace(
        run_once=lambda *, limit: (stop.set(), {"exported": 1})[1],
        has_unresolved_drift=lambda: False,
    )
    sleeps: list[float] = []

    runtime.run_export_loop(worker, stop_event=stop, interval_seconds=12, batch_limit=9, sleep=sleeps.append)

    assert sleeps == []

    calls: list[int] = []
    stop.clear()

    class Worker:
        def run_once(self, *, limit: int):
            calls.append(limit)
            stop.set()
            return {"exported": 1}

        def has_unresolved_drift(self) -> bool:
            return False

    runtime.run_export_loop(Worker(), stop_event=stop, interval_seconds=12, batch_limit=9, sleep=sleeps.append)
    assert calls == [9]


def test_export_loop_marks_recovery_only_after_persistent_drift_is_clear() -> None:
    stop = threading.Event()
    results: list[dict[str, object]] = []

    class Worker:
        def run_once(self, *, limit: int):
            stop.set()
            return {"claimed": 0, "drifted": 0}

        def has_unresolved_drift(self) -> bool:
            return False

    runtime.run_export_loop(
        Worker(),
        stop_event=stop,
        interval_seconds=12,
        batch_limit=9,
        on_result=results.append,
    )

    assert results == [
        {"claimed": 0, "drifted": 0, "recovery_verified": True}
    ]


def test_export_loop_attempts_verified_recovery_before_normal_drain() -> None:
    stop = threading.Event()
    results: list[dict[str, object]] = []

    class Worker:
        def has_unresolved_drift(self) -> bool:
            return True

        def recover_verified_drift(self):
            stop.set()
            return {"examined": 1, "recovered": 0, "remaining": 1, "recovery_verified": False}

        def run_once(self, *, limit: int):
            raise AssertionError("normal drain must remain blocked while drift exists")

    runtime.run_export_loop(
        Worker(),
        stop_event=stop,
        interval_seconds=12,
        batch_limit=9,
        on_result=results.append,
    )

    assert results == [
        {"examined": 1, "recovered": 0, "remaining": 1, "recovery_verified": False}
    ]


def test_financial_export_health_reports_runtime_state_without_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://secret.example/db")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-workbook-123")
    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"private_key":"secret"}')
    runtime._set_state(
        enabled=True,
        running=True,
        ready=True,
        last_result={"claimed": 0, "exported": 0},
        last_error=None,
        drift_latched=False,
        last_drift=None,
    )

    health = runtime.financial_export_health()

    assert health == {
        "enabled": True,
        "running": True,
        "ready": True,
        "last_result": {"claimed": 0, "exported": 0},
        "last_error": None,
        "drift_latched": False,
        "last_drift": None,
        "configured": True,
    }
    assert "secret" not in str(health)


def test_export_runtime_latches_drift_until_explicit_recovery_evidence() -> None:
    runtime._set_state(
        enabled=True,
        running=True,
        ready=True,
        last_result=None,
        last_error=None,
        drift_latched=False,
        last_drift=None,
    )

    runtime._record_export_result({"claimed": 1, "exported": 0, "drifted": 1})
    runtime._record_export_result({"claimed": 0, "exported": 0, "drifted": 0})

    health = runtime.financial_export_health()
    assert health["drift_latched"] is True
    assert health["ready"] is False
    assert health["last_drift"] == {"claimed": 1, "exported": 0, "drifted": 1}

    runtime._record_export_result(
        {
            "claimed": 0,
            "exported": 0,
            "drifted": 0,
            "recovery_verified": True,
        }
    )

    recovered = runtime.financial_export_health()
    assert recovered["drift_latched"] is False
    assert recovered["ready"] is True
    assert recovered["last_drift"] is None


def test_main_registers_financial_export_worker_thread() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "run_financial_export_service" in source
    assert 'name="financial-export-worker"' in source
