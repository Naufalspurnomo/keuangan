from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import financial_export_runtime as runtime


ROOT = Path(__file__).resolve().parents[1]


class FakeWorksheet:
    title = "_CANONICAL_FINANCE_EXPORT"


class FakeSpreadsheet:
    id = "sheet-workbook-123"

    def worksheet(self, title: str):
        assert title == FakeWorksheet.title
        return FakeWorksheet()


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
    monkeypatch.setenv("DATABASE_URL", "postgresql://external.example/db")
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://wrong-state.example/db")
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


def test_build_worker_fails_closed_when_export_is_not_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://external.example/db")
    monkeypatch.setenv("STATE_DATABASE_URL", "postgresql://wrong-state.example/db")
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-workbook-123")
    monkeypatch.setenv("FINANCIAL_EXPORT_PROTECTED_DESTINATION", "false")

    with pytest.raises(RuntimeError, match="protected destination"):
        runtime.build_export_worker()


def test_export_loop_is_stop_event_driven_and_runs_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()
    worker = SimpleNamespace(run_once=lambda *, limit: (stop.set(), {"exported": 1})[1])
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

    runtime.run_export_loop(Worker(), stop_event=stop, interval_seconds=12, batch_limit=9, sleep=sleeps.append)
    assert calls == [9]


def test_main_registers_financial_export_worker_thread() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "run_financial_export_service" in source
    assert 'name="financial-export-worker"' in source
