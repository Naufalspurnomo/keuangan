from __future__ import annotations

from copy import deepcopy

import pytest

from services.finance_write_authority import (
    CanonicalWriteUnavailable,
    FinanceWriteAuthorityGateway,
    canonical_finance_writes_enabled,
)


class FakeResolver:
    def __init__(self) -> None:
        self.quarantined = []
        self.wallets = {
            "CV HB(101)": (
                "34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b",
                "d3261754-6ee5-5d37-b0e2-79614da60abb",
            ),
            "TX SBY(216)": (
                "c23a1506-50d2-55a9-9469-8744b18fd85b",
                "9f91cd70-58b6-52c8-aeaa-55ebf3006d13",
            ),
            "TX BALI(087)": (
                "07743a6c-1ad0-5c00-9d96-0beaee4b8e01",
                "0e21a9d9-4bda-5cb2-965b-bc2202e981ce",
            ),
        }
        self.project_id = "00000000-0000-4000-8000-000000000501"

    def resolve_wallet(self, label):
        return self.wallets.get(label)

    def resolve_project(self, project_id, project_label):
        if project_id == self.project_id or project_label == "Mapped Project":
            return self.project_id
        return None

    def quarantine(self, command, reason_code):
        self.quarantined.append((deepcopy(dict(command)), reason_code))
        return "00000000-0000-4000-8000-000000000901"


class FakeCanonicalFinance:
    def __init__(self, *, fail=False) -> None:
        self.fail = fail
        self.calls = []

    def create_transaction(self, payload, *, actor):
        self.calls.append((deepcopy(dict(payload)), deepcopy(dict(actor))))
        if self.fail:
            raise RuntimeError("postgres unavailable")
        return {"record": {"id": "00000000-0000-4000-8000-000000000601"}, "duplicate": False}


class FakeDebtService:
    def __init__(self) -> None:
        self.calls = []

    def create_debt(self, payload, *, actor):
        self.calls.append((deepcopy(dict(payload)), deepcopy(dict(actor))))
        return {"debt_id": "00000000-0000-4000-8000-000000000701", "duplicate": False}


def transaction_command(**overrides):
    value = {
        "kind": "transaction",
        "idempotency_key": "wa:message:0123456789abcdef",
        "scope": "project",
        "project_id": "00000000-0000-4000-8000-000000000501",
        "project_label": "Mapped Project",
        "wallet_label": "CV HB(101)",
        "transaction_type": "outflow",
        "amount": 250_000,
        "currency": "IDR",
        "category": "Material",
        "description": "Beli material",
        "occurred_at": "2026-11-12T00:00:00+00:00",
        "source": "whatsapp",
        "source_reference": "wa-message-1",
        "evidence": {},
        "actor": {"id": "owner:960074500", "role": "boss", "channel": "whatsapp"},
    }
    value.update(overrides)
    return value


def debt_command(**overrides):
    value = {
        "kind": "debt",
        "idempotency_key": "wa:debt:0123456789abcdef",
        "lender_wallet_label": "CV HB(101)",
        "borrower_wallet_label": "TX SBY(216)",
        "project_id": None,
        "project_label": None,
        "principal": 500_000,
        "currency": "IDR",
        "occurred_at": "2026-11-12T00:00:00+00:00",
        "due_at": None,
        "description": "Dana talangan",
        "actor": {"id": "owner:960074500", "role": "boss", "channel": "whatsapp"},
    }
    value.update(overrides)
    return value


def test_flag_is_strict_and_defaults_false():
    assert canonical_finance_writes_enabled({}) is False
    assert canonical_finance_writes_enabled({"CANONICAL_FINANCE_WRITES_ENABLED": "true"}) is True
    assert canonical_finance_writes_enabled({"CANONICAL_FINANCE_WRITES_ENABLED": "1"}) is True
    assert canonical_finance_writes_enabled({"CANONICAL_FINANCE_WRITES_ENABLED": "yes"}) is False


def test_disabled_executes_legacy_once_without_touching_canonical():
    finance = FakeCanonicalFinance()
    legacy = []
    gateway = FinanceWriteAuthorityGateway(
        enabled=False,
        resolver=FakeResolver(),
        finance_service=finance,
        debt_service=FakeDebtService(),
    )

    result = gateway.dispatch(transaction_command(), legacy_write=lambda: legacy.append(1) or {"row": 9})

    assert result == {"authority": "google_sheets", "result": {"row": 9}}
    assert legacy == [1]
    assert finance.calls == []


def test_enabled_routes_transaction_once_and_never_calls_legacy():
    resolver = FakeResolver()
    finance = FakeCanonicalFinance()
    legacy = []
    gateway = FinanceWriteAuthorityGateway(
        enabled=True,
        resolver=resolver,
        finance_service=finance,
        debt_service=FakeDebtService(),
    )

    result = gateway.dispatch(transaction_command(), legacy_write=lambda: legacy.append(1))

    assert legacy == []
    assert result["authority"] == "postgresql"
    payload, actor = finance.calls[0]
    assert payload["wallet_id"] == resolver.wallets["CV HB(101)"][0]
    assert payload["business_unit_id"] == resolver.wallets["CV HB(101)"][1]
    assert payload["project_id"] == resolver.project_id
    assert "project_label" not in payload
    assert actor["id"] == "owner:960074500"


def test_unknown_wallet_and_unmapped_project_quarantine_without_any_write():
    resolver = FakeResolver()
    finance = FakeCanonicalFinance()
    gateway = FinanceWriteAuthorityGateway(
        enabled=True,
        resolver=resolver,
        finance_service=finance,
        debt_service=FakeDebtService(),
    )

    wallet_result = gateway.dispatch(
        transaction_command(wallet_label="Unknown"), legacy_write=lambda: pytest.fail("legacy called")
    )
    project_result = gateway.dispatch(
        transaction_command(project_id=None, project_label="Unknown Project"),
        legacy_write=lambda: pytest.fail("legacy called"),
    )

    assert wallet_result["status"] == "quarantined"
    assert project_result["status"] == "quarantined"
    assert [item[1] for item in resolver.quarantined] == ["unknown_wallet", "unmapped_project"]
    assert finance.calls == []


def test_active_dependency_failure_never_falls_back_to_sheets():
    legacy = []
    gateway = FinanceWriteAuthorityGateway(
        enabled=True,
        resolver=FakeResolver(),
        finance_service=FakeCanonicalFinance(fail=True),
        debt_service=FakeDebtService(),
    )

    with pytest.raises(CanonicalWriteUnavailable, match="canonical finance write failed"):
        gateway.dispatch(transaction_command(), legacy_write=lambda: legacy.append(1))

    assert legacy == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"idempotency_key": ""}, "missing_idempotency"),
        ({"actor": None}, "missing_actor"),
        ({"occurred_at": "2026-11-12"}, "missing_timestamp"),
    ],
)
def test_missing_canonical_metadata_is_durably_quarantined(changes, reason):
    resolver = FakeResolver()
    finance = FakeCanonicalFinance()
    gateway = FinanceWriteAuthorityGateway(
        enabled=True,
        resolver=resolver,
        finance_service=finance,
        debt_service=FakeDebtService(),
    )

    result = gateway.dispatch(
        transaction_command(**changes), legacy_write=lambda: pytest.fail("legacy called")
    )

    assert result["status"] == "quarantined"
    assert result["reason_code"] == reason
    assert resolver.quarantined[0][1] == reason
    assert finance.calls == []


def test_debt_is_one_service_command_not_multiple_transaction_writes():
    resolver = FakeResolver()
    finance = FakeCanonicalFinance()
    debt = FakeDebtService()
    gateway = FinanceWriteAuthorityGateway(
        enabled=True,
        resolver=resolver,
        finance_service=finance,
        debt_service=debt,
    )

    result = gateway.dispatch(debt_command(), legacy_write=lambda: pytest.fail("legacy called"))

    assert result["authority"] == "postgresql"
    assert finance.calls == []
    assert len(debt.calls) == 1
    payload, _actor = debt.calls[0]
    assert payload["lender_wallet_id"] == resolver.wallets["CV HB(101)"][0]
    assert payload["borrower_wallet_id"] == resolver.wallets["TX SBY(216)"][0]
    assert payload["lender_business_unit_id"] == resolver.wallets["CV HB(101)"][1]
    assert payload["borrower_business_unit_id"] == resolver.wallets["TX SBY(216)"][1]
