from __future__ import annotations

from copy import deepcopy

import pytest

from services.whatsapp_finance_commands import (
    ActorNotAuthorized,
    dispatch_confirmed_finance_batch,
    dispatch_if_canonical_enabled,
    resolve_whatsapp_actor,
)


class FakeApp:
    def __init__(self, *, enabled, gateway=None):
        self.config = {"CANONICAL_FINANCE_WRITES_ENABLED": enabled}
        self.extensions = {}
        if gateway is not None:
            self.extensions["finance_write_authority_gateway"] = gateway


class RecordingGateway:
    def __init__(self, *, quarantine_index=None, fail_index=None):
        self.calls = []
        self.quarantine_index = quarantine_index
        self.fail_index = fail_index

    def dispatch(self, command, *, legacy_write):
        index = len(self.calls)
        self.calls.append((deepcopy(command), legacy_write))
        if index == self.fail_index:
            raise RuntimeError("canonical unavailable")
        if index == self.quarantine_index:
            return {
                "authority": "postgresql",
                "status": "quarantined",
                "reason_code": "unmapped_project",
                "quarantine_id": "00000000-0000-4000-8000-000000000701",
            }
        return {
            "authority": "postgresql",
            "status": "committed",
            "result": {"duplicate": False, "transaction": {"id": f"tx-{index}"}},
        }


def transactions():
    return [
        {
            "jumlah": 125_000,
            "keterangan": "Material A",
            "tipe": "Pengeluaran",
            "tanggal": "2026-11-12",
            "message_id": "message-1",
            "nama_projek": "Project Alpha",
            "category": "Bahan Alat",
        },
        {
            "jumlah": 75_000,
            "keterangan": "Material B",
            "tipe": "Pengeluaran",
            "tanggal": "2026-11-12",
            "message_id": "message-2",
            "nama_projek": "Project Alpha",
            "category": "Bahan Alat",
        },
    ]


def test_actor_role_requires_explicit_stable_sender_registry():
    environ = {
        "FINANCE_BOSS_SENDER_IDS": "6281212042709, telegram:960074500",
        "FINANCE_ADMIN_SENDER_IDS": "6281111111111",
    }
    assert resolve_whatsapp_actor("6281212042709", environ=environ) == {
        "id": "6281212042709",
        "role": "boss",
        "channel": "whatsapp",
    }
    assert resolve_whatsapp_actor("6281111111111", environ=environ)["role"] == "admin"
    with pytest.raises(ActorNotAuthorized):
        resolve_whatsapp_actor("Unknown Display Name", environ=environ)


def test_runtime_seam_is_noop_when_inactive_and_fail_closed_when_active_unready():
    kwargs = dict(
        sender_id="6281212042709",
        event_id="wamid-owner-event-000000",
        transactions=transactions(),
        wallet_label="TX SBY(216)",
        project_id=None,
        project_label="Project Alpha",
        source="whatsapp",
        environ={"FINANCE_BOSS_SENDER_IDS": "6281212042709"},
    )
    assert dispatch_if_canonical_enabled(FakeApp(enabled=False), **kwargs) is None
    with pytest.raises(RuntimeError, match="gateway is unavailable"):
        dispatch_if_canonical_enabled(FakeApp(enabled=True), **kwargs)


def test_runtime_seam_active_uses_registered_gateway_and_explicit_actor_role():
    gateway = RecordingGateway()
    result = dispatch_if_canonical_enabled(
        FakeApp(enabled=True, gateway=gateway),
        sender_id="6281212042709",
        event_id="wamid-owner-event-000005",
        transactions=transactions()[:1],
        wallet_label="TX SBY(216)",
        project_id=None,
        project_label="Project Alpha",
        source="whatsapp",
        environ={"FINANCE_BOSS_SENDER_IDS": "6281212042709"},
    )
    assert result["status"] == "committed"
    assert gateway.calls[0][0]["actor"] == {
        "id": "6281212042709",
        "role": "boss",
        "channel": "whatsapp",
    }


def test_batch_routes_each_expense_then_one_atomic_debt_with_stable_keys():
    gateway = RecordingGateway()
    actor = {"id": "6281212042709", "role": "boss", "channel": "whatsapp"}

    result = dispatch_confirmed_finance_batch(
        gateway=gateway,
        event_id="wamid-owner-event-000001",
        transactions=transactions(),
        wallet_label="TX SBY(216)",
        project_id=None,
        project_label="Project Alpha",
        actor=actor,
        source="whatsapp",
        debt_source_wallet_label="CV HB(101)",
    )

    assert result == {"status": "committed", "transaction_count": 2, "debt_committed": True}
    commands = [call[0] for call in gateway.calls]
    assert [command["kind"] for command in commands] == ["transaction", "transaction", "debt"]
    assert [command["idempotency_key"] for command in commands] == [
        "whatsapp:wamid-owner-event-000001:item:message-1",
        "whatsapp:wamid-owner-event-000001:item:message-2",
        "whatsapp:wamid-owner-event-000001:debt",
    ]
    assert commands[0]["occurred_at"] == "2026-11-12T00:00:00+07:00"
    assert commands[0]["evidence"]["occurred_at_precision"] == "date"
    assert commands[2]["lender_wallet_label"] == "CV HB(101)"
    assert commands[2]["borrower_wallet_label"] == "TX SBY(216)"
    assert commands[2]["principal"] == 200_000
    for _command, legacy_write in gateway.calls:
        with pytest.raises(AssertionError):
            legacy_write()


def test_quarantine_stops_batch_before_later_items_or_debt():
    gateway = RecordingGateway(quarantine_index=0)
    result = dispatch_confirmed_finance_batch(
        gateway=gateway,
        event_id="wamid-owner-event-000002",
        transactions=transactions(),
        wallet_label="TX SBY(216)",
        project_id=None,
        project_label="Unknown Project",
        actor={"id": "6281212042709", "role": "boss", "channel": "whatsapp"},
        source="whatsapp",
        debt_source_wallet_label="CV HB(101)",
    )

    assert result["status"] == "quarantined"
    assert result["reason_code"] == "unmapped_project"
    assert len(gateway.calls) == 1


def test_later_invalid_item_and_mixed_project_debt_write_nothing():
    gateway = RecordingGateway()
    invalid_rows = transactions()
    invalid_rows[1]["jumlah"] = 0
    common = dict(
        gateway=gateway,
        event_id="wamid-owner-event-000006",
        wallet_label="TX SBY(216)",
        project_id=None,
        project_label="Project Alpha",
        actor={"id": "6281212042709", "role": "boss", "channel": "whatsapp"},
        source="whatsapp",
        debt_source_wallet_label="CV HB(101)",
    )
    assert dispatch_confirmed_finance_batch(transactions=invalid_rows, **common) == {
        "status": "quarantined",
        "reason_code": "invalid_amount",
    }
    assert gateway.calls == []

    mixed_rows = transactions()
    mixed_rows[1]["nama_projek"] = "Project Beta"
    assert dispatch_confirmed_finance_batch(transactions=mixed_rows, **common) == {
        "status": "quarantined",
        "reason_code": "ambiguous_debt_project",
    }
    assert gateway.calls == []


def test_auto_scope_routes_general_rows_without_fabricating_project_uuid():
    gateway = RecordingGateway()
    rows = transactions()
    for item in rows:
        item["nama_projek"] = "Saldo Umum"
    result = dispatch_confirmed_finance_batch(
        gateway=gateway,
        event_id="wamid-owner-event-000007",
        transactions=rows,
        wallet_label="CV HB(101)",
        project_id=None,
        project_label=None,
        actor={"id": "6281212042709", "role": "boss", "channel": "whatsapp"},
        source="whatsapp",
        scope="auto",
    )
    assert result["status"] == "committed"
    assert {call[0]["scope"] for call in gateway.calls} == {"group"}
    assert all(call[0]["project_id"] is None for call in gateway.calls)


def test_missing_or_invalid_date_is_quarantined_without_gateway_write():
    gateway = RecordingGateway()
    rows = transactions()
    rows[0]["tanggal"] = "12/11/2026"
    result = dispatch_confirmed_finance_batch(
        gateway=gateway,
        event_id="wamid-owner-event-000003",
        transactions=rows,
        wallet_label="TX SBY(216)",
        project_id=None,
        project_label="Project Alpha",
        actor={"id": "6281212042709", "role": "boss", "channel": "whatsapp"},
        source="whatsapp",
    )

    assert result == {"status": "quarantined", "reason_code": "missing_transaction_date"}
    assert gateway.calls == []


def test_same_input_reuses_identical_keys_for_resumable_replay():
    gateway = RecordingGateway(fail_index=1)
    kwargs = dict(
        gateway=gateway,
        event_id="wamid-owner-event-000004",
        transactions=transactions(),
        wallet_label="TX SBY(216)",
        project_id=None,
        project_label="Project Alpha",
        actor={"id": "6281212042709", "role": "boss", "channel": "whatsapp"},
        source="whatsapp",
    )
    with pytest.raises(RuntimeError):
        dispatch_confirmed_finance_batch(**kwargs)
    first_keys = [call[0]["idempotency_key"] for call in gateway.calls]

    replay = RecordingGateway()
    kwargs["gateway"] = replay
    dispatch_confirmed_finance_batch(**kwargs)
    assert [call[0]["idempotency_key"] for call in replay.calls] == [
        first_keys[0],
        "whatsapp:wamid-owner-event-000004:item:message-2",
    ]
