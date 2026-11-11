from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from services.interwallet_debt_service import (
    DebtConflict,
    DebtValidationError,
    InMemoryInterwalletDebtRepository,
    InterwalletDebtService,
)


NOW = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
LENDER_WALLET = "00000000-0000-4000-8000-000000000201"
BORROWER_WALLET = "00000000-0000-4000-8000-000000000202"
LENDER_UNIT = "00000000-0000-4000-8000-000000000301"
BORROWER_UNIT = "00000000-0000-4000-8000-000000000302"
PROJECT_ID = "00000000-0000-4000-8000-000000000101"
ACTOR = {"id": "admin-1", "role": "admin", "channel": "dashboard"}


def create_payload(**changes):
    value = {
        "idempotency_key": "debt-create-0000001",
        "lender_wallet_id": LENDER_WALLET,
        "borrower_wallet_id": BORROWER_WALLET,
        "lender_business_unit_id": LENDER_UNIT,
        "borrower_business_unit_id": BORROWER_UNIT,
        "project_id": PROJECT_ID,
        "principal": 1_000_000,
        "currency": "IDR",
        "occurred_at": NOW.isoformat(),
        "due_at": "2026-12-11T10:00:00+00:00",
        "description": "Pendanaan produksi sementara",
    }
    value.update(changes)
    return value


def make_service():
    repository = InMemoryInterwalletDebtRepository()
    return InterwalletDebtService(repository), repository


def assert_internal_postings_balanced(event, amount):
    postings = event["postings"]
    assert sum(item["signed_amount"] for item in postings) == 0
    assert sum(item["signed_amount"] for item in postings if item["account_class"] == "cash") == 0
    assert {item["account_class"] for item in postings} == {"cash", "receivable", "payable"}
    assert not ({"revenue", "expense"} & {item["account_class"] for item in postings})
    assert {abs(item["signed_amount"]) for item in postings} == {amount}


def test_create_debt_is_idempotent_balanced_and_neutral_to_group_cash_and_profit():
    service, repository = make_service()

    created = service.create_debt(create_payload(), actor=ACTOR)
    replay = service.create_debt(create_payload(), actor=ACTOR)

    assert created["duplicate"] is False
    assert replay == {**created, "duplicate": True}
    assert UUID(created["debt"]["id"])
    assert created["debt"]["outstanding"] == 1_000_000
    assert created["debt"]["status"] == "open"
    assert_internal_postings_balanced(created["debt"]["events"][0], 1_000_000)
    assert repository.outbox_count == 1


def test_partial_then_full_repayment_reduces_outstanding_without_pnl():
    service, _ = make_service()
    debt = service.create_debt(create_payload(), actor=ACTOR)["debt"]

    partial = service.repay_debt(
        debt["id"],
        {
            "idempotency_key": "debt-repay-0000001",
            "expected_version": 1,
            "amount": 250_000,
            "occurred_at": "2026-11-20T10:00:00+00:00",
            "description": "Cicilan pertama",
        },
        actor=ACTOR,
    )["debt"]
    paid = service.repay_debt(
        debt["id"],
        {
            "idempotency_key": "debt-repay-0000002",
            "expected_version": 2,
            "amount": 750_000,
            "occurred_at": "2026-11-25T10:00:00+00:00",
            "description": "Pelunasan",
        },
        actor=ACTOR,
    )["debt"]

    assert partial["outstanding"] == 750_000
    assert partial["status"] == "open"
    assert_internal_postings_balanced(partial["events"][-1], 250_000)
    assert paid["outstanding"] == 0
    assert paid["status"] == "paid"
    assert_internal_postings_balanced(paid["events"][-1], 750_000)


def test_repayment_cannot_exceed_outstanding():
    service, _ = make_service()
    debt = service.create_debt(create_payload(), actor=ACTOR)["debt"]

    with pytest.raises(DebtConflict, match="outstanding"):
        service.repay_debt(
            debt["id"],
            {
                "idempotency_key": "debt-repay-0000003",
                "expected_version": 1,
                "amount": 1_000_001,
                "occurred_at": NOW.isoformat(),
                "description": "Invalid repayment",
            },
            actor=ACTOR,
        )


def test_correction_replaces_event_effect_and_preserves_audit_history():
    service, _ = make_service()
    debt = service.create_debt(create_payload(), actor=ACTOR)["debt"]
    repaid = service.repay_debt(
        debt["id"],
        {
            "idempotency_key": "debt-repay-0000004",
            "expected_version": 1,
            "amount": 250_000,
            "occurred_at": NOW.isoformat(),
            "description": "Cicilan salah input",
        },
        actor=ACTOR,
    )["debt"]
    repayment = repaid["events"][-1]

    corrected = service.correct_event(
        debt["id"],
        repayment["id"],
        {
            "idempotency_key": "debt-correct-000001",
            "expected_version": 2,
            "amount": 200_000,
            "reason": "Nominal bukti bank 200 ribu",
            "occurred_at": NOW.isoformat(),
        },
        actor=ACTOR,
    )["debt"]

    correction = corrected["events"][-1]
    assert correction["event_type"] == "correction"
    assert correction["corrects_event_id"] == repayment["id"]
    assert correction["corrected_event_type"] == "repayment"
    assert corrected["outstanding"] == 800_000
    assert len(corrected["events"]) == 3
    assert_internal_postings_balanced(correction, 200_000)


def test_reversal_of_repayment_restores_outstanding_and_is_single_use():
    service, _ = make_service()
    debt = service.create_debt(create_payload(), actor=ACTOR)["debt"]
    repayment = service.repay_debt(
        debt["id"],
        {
            "idempotency_key": "debt-repay-0000005",
            "expected_version": 1,
            "amount": 300_000,
            "occurred_at": NOW.isoformat(),
            "description": "Cicilan yang dibatalkan",
        },
        actor=ACTOR,
    )["debt"]["events"][-1]

    reversed_debt = service.reverse_event(
        debt["id"],
        repayment["id"],
        {
            "idempotency_key": "debt-reverse-00001",
            "expected_version": 2,
            "reason": "Transfer dikembalikan bank",
            "occurred_at": NOW.isoformat(),
        },
        actor=ACTOR,
    )["debt"]

    assert reversed_debt["outstanding"] == 1_000_000
    assert reversed_debt["events"][-1]["reverses_event_id"] == repayment["id"]
    with pytest.raises(DebtConflict, match="already reversed"):
        service.reverse_event(
            debt["id"],
            repayment["id"],
            {
                "idempotency_key": "debt-reverse-00002",
                "expected_version": 3,
                "reason": "Tidak boleh dua kali",
                "occurred_at": NOW.isoformat(),
            },
            actor=ACTOR,
        )


def test_reversing_disbursement_requires_zero_repayment_exposure():
    service, _ = make_service()
    debt = service.create_debt(create_payload(), actor=ACTOR)["debt"]
    service.repay_debt(
        debt["id"],
        {
            "idempotency_key": "debt-repay-0000006",
            "expected_version": 1,
            "amount": 100_000,
            "occurred_at": NOW.isoformat(),
            "description": "Sudah ada cicilan",
        },
        actor=ACTOR,
    )

    with pytest.raises(DebtConflict, match="repayment"):
        service.reverse_event(
            debt["id"],
            debt["events"][0]["id"],
            {
                "idempotency_key": "debt-reverse-00003",
                "expected_version": 2,
                "reason": "Tidak boleh membatalkan pokok setelah cicilan",
                "occurred_at": NOW.isoformat(),
            },
            actor=ACTOR,
        )


@pytest.mark.parametrize(
    "changes, error",
    [
        ({"borrower_wallet_id": LENDER_WALLET}, "wallet"),
        ({"principal": 0}, "principal"),
        ({"currency": "USD"}, "currency"),
        ({"project_id": "Project Alpha"}, "project_id"),
        ({"due_at": "2026-01-01T00:00:00+00:00"}, "due_at"),
    ],
)
def test_create_debt_validation_is_strict(changes, error):
    service, _ = make_service()

    with pytest.raises(DebtValidationError, match=error):
        service.create_debt(create_payload(**changes), actor=ACTOR)
