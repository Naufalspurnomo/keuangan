from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy

import pytest

from services.financial_export_worker import (
    ClaimedExport,
    ExportWorker,
    RemoteExportDrift,
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class CrashAfterRemoteWrite(BaseException):
    pass


class FakeOutbox:
    def __init__(self, row: ClaimedExport) -> None:
        self.row = row
        self.status = "pending"
        self.ack_count = 0
        self.failed = []
        self.drifted = []

    def claim(self, *, limit: int, lease_seconds: int):
        if self.status in {"pending", "exporting"}:
            self.status = "exporting"
            return [self.row]
        return []

    def has_unresolved_drift(self) -> bool:
        return self.status == "drifted"

    def acknowledge(self, row_id: str, claim_token: str, remote_locator: str) -> bool:
        assert row_id == self.row.id
        assert claim_token == self.row.claim_token
        self.status = "exported"
        self.ack_count += 1
        return True

    def fail(self, row_id: str, claim_token: str, error: str) -> bool:
        self.status = "failed"
        self.failed.append((row_id, claim_token, error))
        return True

    def mark_drifted(self, row_id: str, claim_token: str, error: str) -> bool:
        self.status = "drifted"
        self.drifted.append((row_id, claim_token, error))
        return True


class FakeRemote:
    def __init__(self) -> None:
        self.rows = {}
        self.writes = 0

    def read(self, ordinal: int):
        value = self.rows.get(ordinal)
        return deepcopy(value) if value is not None else None

    def write(self, ordinal: int, document):
        self.writes += 1
        self.rows[ordinal] = deepcopy(dict(document))


def row(*, export_ordinal: int = 1) -> ClaimedExport:
    payload = {
        "schema_version": "canonical.finance.transaction.v1",
        "id": "00000000-0000-4000-8000-000000000101",
        "version": 1,
        "amount": 125_000,
    }
    return ClaimedExport(
        id="00000000-0000-4000-8000-000000000201",
        export_ordinal=export_ordinal,
        export_key="transaction:00000000-0000-4000-8000-000000000101:v1",
        aggregate_type="transaction",
        aggregate_id="00000000-0000-4000-8000-000000000101",
        aggregate_version=1,
        payload=payload,
        payload_sha256=hashlib.sha256(_canonical(payload).encode()).hexdigest(),
        created_at="2026-11-12T00:00:00Z",
        claim_token="00000000-0000-4000-8000-000000000301",
    )


def test_crash_after_remote_write_replays_without_duplicate_effective_row() -> None:
    outbox = FakeOutbox(row())
    remote = FakeRemote()
    first = ExportWorker(
        outbox=outbox,
        remote=remote,
        protected_destination=True,
        after_remote_write=lambda _row: (_ for _ in ()).throw(CrashAfterRemoteWrite()),
    )

    with pytest.raises(CrashAfterRemoteWrite):
        first.run_once()

    assert outbox.status == "exporting"
    assert outbox.ack_count == 0
    assert remote.writes == 1
    assert len(remote.rows) == 1

    replay = ExportWorker(outbox=outbox, remote=remote, protected_destination=True)
    result = replay.run_once()

    assert result == {"claimed": 1, "written": 0, "unchanged": 1, "exported": 1, "drifted": 0, "failed": 0}
    assert outbox.ack_count == 1
    assert remote.writes == 1
    assert len(remote.rows) == 1


def test_manual_remote_drift_is_marked_and_never_overwritten() -> None:
    claimed = row()
    outbox = FakeOutbox(claimed)
    remote = FakeRemote()
    expected = claimed.document
    remote.rows[claimed.export_ordinal] = {**expected, "payload_json": "{}"}

    result = ExportWorker(outbox=outbox, remote=remote, protected_destination=True).run_once()

    assert result["drifted"] == 1
    assert result["exported"] == 0
    assert outbox.status == "drifted"
    assert remote.writes == 0
    assert outbox.drifted


def test_existing_drift_blocks_new_claims() -> None:
    class DriftedOutbox:
        def has_unresolved_drift(self) -> bool:
            return True

        def claim(self, *, limit: int, lease_seconds: int):
            raise AssertionError("unresolved drift must block new claims")

    result = ExportWorker(
        outbox=DriftedOutbox(),
        remote=FakeRemote(),
        protected_destination=True,
    ).run_once()

    assert result == {
        "claimed": 0,
        "written": 0,
        "unchanged": 0,
        "exported": 0,
        "drifted": 0,
        "failed": 0,
    }


def test_recovery_only_clears_drift_after_exact_remote_readback() -> None:
    claimed = row()

    class RecoverableOutbox(FakeOutbox):
        def drifted_rows(self):
            return [self.row] if self.status == "drifted" else []

        def resolve_drift(self, row_id: str, remote_locator: str) -> bool:
            assert row_id == self.row.id
            assert remote_locator.endswith(self.row.document["row_sha256"])
            self.status = "exported"
            return True

    outbox = RecoverableOutbox(claimed)
    outbox.status = "drifted"
    remote = FakeRemote()
    worker = ExportWorker(outbox=outbox, remote=remote, protected_destination=True)

    assert worker.recover_verified_drift() == {
        "examined": 1, "recovered": 0, "remaining": 1, "recovery_verified": False,
    }
    assert outbox.status == "drifted"

    remote.rows[claimed.export_ordinal] = claimed.document
    assert worker.recover_verified_drift() == {
        "examined": 1, "recovered": 1, "remaining": 0, "recovery_verified": True,
    }
    assert outbox.status == "exported"


def test_worker_guard_wraps_the_complete_remote_write_and_ack_cycle() -> None:
    class GuardedOutbox(FakeOutbox):
        def __init__(self, claimed: ClaimedExport) -> None:
            super().__init__(claimed)
            self.guard_active = False
            self.events: list[str] = []

        @contextmanager
        def worker_guard(self):
            self.guard_active = True
            self.events.append("enter")
            try:
                yield
            finally:
                self.events.append("exit")
                self.guard_active = False

        def acknowledge(self, row_id: str, claim_token: str, remote_locator: str) -> bool:
            assert self.guard_active
            self.events.append("ack")
            return super().acknowledge(row_id, claim_token, remote_locator)

    outbox = GuardedOutbox(row())

    class GuardedRemote(FakeRemote):
        def read(self, ordinal: int):
            assert outbox.guard_active
            outbox.events.append("read")
            return super().read(ordinal)

        def write(self, ordinal: int, document):
            assert outbox.guard_active
            outbox.events.append("write")
            super().write(ordinal, document)

    result = ExportWorker(outbox=outbox, remote=GuardedRemote(), protected_destination=True).run_once()

    assert result["exported"] == 1
    assert outbox.events == ["enter", "read", "write", "read", "ack", "exit"]


def test_new_drift_stops_the_rest_of_the_claimed_batch() -> None:
    first = row(export_ordinal=1)
    second = row(export_ordinal=2)

    class BatchOutbox:
        def __init__(self) -> None:
            self.drifted = []

        def has_unresolved_drift(self) -> bool:
            return False

        def claim(self, *, limit: int, lease_seconds: int):
            return [first, second]

        def mark_drifted(self, row_id: str, claim_token: str, error: str) -> bool:
            self.drifted.append((row_id, claim_token, error))
            return True

        def acknowledge(self, row_id: str, claim_token: str, remote_locator: str) -> bool:
            raise AssertionError("rows after drift must not be exported")

        def fail(self, row_id: str, claim_token: str, error: str) -> bool:
            raise AssertionError("rows after drift must remain untouched")

    outbox = BatchOutbox()
    remote = FakeRemote()
    remote.rows[first.export_ordinal] = {**first.document, "payload_json": "{}"}

    result = ExportWorker(
        outbox=outbox,
        remote=remote,
        protected_destination=True,
    ).run_once()

    assert result["claimed"] == 2
    assert result["drifted"] == 1
    assert result["exported"] == 0
    assert second.export_ordinal not in remote.rows
    assert len(outbox.drifted) == 1


def test_postgres_store_uses_qualified_returning_and_token_guarded_ack() -> None:
    from services.financial_export_worker import PostgresExportOutbox

    assert "outbox.id" in PostgresExportOutbox._CLAIM_SQL
    assert "outbox.claim_token" in PostgresExportOutbox._CLAIM_SQL
    assert "NOT EXISTS" in PostgresExportOutbox._CLAIM_SQL
    assert "status = 'drifted'" in PostgresExportOutbox._CLAIM_SQL


class FakeSpreadsheet:
    id = "dedicated-export-workbook"


class FakeWorksheet:
    def __init__(self) -> None:
        self.title = "canonical_financial_export_v1"
        self.spreadsheet = FakeSpreadsheet()
        self.rows = {}
        self.updates = []

    def row_values(self, row_number: int):
        return list(self.rows.get(row_number, []))

    def update(self, range_name: str, values, *, value_input_option: str):
        row_number = int(range_name.split(":", 1)[0][1:])
        self.rows[row_number] = list(values[0])
        self.updates.append((range_name, deepcopy(values), value_input_option))


def test_google_sheet_adapter_uses_frozen_header_deterministic_row_and_raw_write() -> None:
    from services.financial_export_worker import GoogleSheetsRemoteExport

    worksheet = FakeWorksheet()
    remote = GoogleSheetsRemoteExport(
        worksheet,
        expected_workbook_id="dedicated-export-workbook",
        expected_title="canonical_financial_export_v1",
        ensure_header=True,
    )
    expected = row(export_ordinal=3).document

    remote.write(3, expected)

    assert worksheet.updates[0][0] == "A1:J1"
    assert worksheet.updates[1][0] == "A4:J4"
    assert all(update[2] == "RAW" for update in worksheet.updates)
    assert remote.read(3) == expected


def test_google_sheet_adapter_rejects_wrong_tab_and_header_drift() -> None:
    from services.financial_export_worker import GoogleSheetsRemoteExport

    wrong = FakeWorksheet()
    wrong.title = "legacy-primary"
    with pytest.raises(RemoteExportDrift, match="tab"):
        GoogleSheetsRemoteExport(
            wrong,
            expected_workbook_id="dedicated-export-workbook",
            expected_title="canonical_financial_export_v1",
        )

    drifted = FakeWorksheet()
    drifted.rows[1] = ["wrong"]
    with pytest.raises(RemoteExportDrift, match="header"):
        GoogleSheetsRemoteExport(
            drifted,
            expected_workbook_id="dedicated-export-workbook",
            expected_title="canonical_financial_export_v1",
            ensure_header=True,
        )


def test_drift_audit_detects_missing_duplicate_reordered_and_unexpected_rows() -> None:
    from services.financial_export_worker import audit_remote_export

    first = row(export_ordinal=1)
    second_payload = {
        "schema_version": "canonical.finance.transaction.v1",
        "id": "00000000-0000-4000-8000-000000000102",
        "version": 1,
        "amount": 250_000,
    }
    second = ClaimedExport(
        id="00000000-0000-4000-8000-000000000202",
        export_ordinal=2,
        export_key="transaction:00000000-0000-4000-8000-000000000102:v1",
        aggregate_type="transaction",
        aggregate_id="00000000-0000-4000-8000-000000000102",
        aggregate_version=1,
        payload=second_payload,
        payload_sha256=hashlib.sha256(_canonical(second_payload).encode()).hexdigest(),
        created_at="2026-11-12T00:00:00Z",
        claim_token="00000000-0000-4000-8000-000000000302",
    )
    remote = FakeRemote()
    remote.rows[1] = second.document
    remote.rows[2] = second.document
    remote.rows[3] = {**second.document, "export_key": "unexpected"}

    result = audit_remote_export(
        [first, second], remote=remote, remote_max_ordinal=3
    )

    assert result["ready"] is False
    assert result["missing_ordinals"] == [1]
    assert result["reordered_ordinals"] == [1]
    assert result["unexpected_ordinals"] == [3]
    assert result["duplicate_keys"] == {second.export_key: [1, 2]}
    assert result["lag_rows"] == 1


def test_worker_rejects_unprotected_destination_before_claim() -> None:
    outbox = FakeOutbox(row())
    with pytest.raises(RemoteExportDrift, match="protected"):
        ExportWorker(outbox=outbox, remote=FakeRemote(), protected_destination=False).run_once()
    assert outbox.status == "pending"
