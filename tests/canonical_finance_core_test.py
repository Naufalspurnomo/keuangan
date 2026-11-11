from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import UUID

import pytest

from services.canonical_finance import (
    CanonicalFinanceService,
    FinanceConflict,
    FinanceValidationError,
)
from services.financial_transaction_repository import InMemoryFinancialRepository


NOW = datetime(2026, 11, 11, 9, 30, tzinfo=timezone.utc)
PROJECT_ID = "00000000-0000-4000-8000-000000000101"
WALLET_ID = "00000000-0000-4000-8000-000000000201"
UNIT_ID = "00000000-0000-4000-8000-000000000301"
ACTOR = {"id": "boss-1", "role": "boss", "channel": "dashboard"}


def payload(**changes):
    value = {
        "idempotency_key": "txn-create-00000001",
        "scope": "project",
        "project_id": PROJECT_ID,
        "wallet_id": WALLET_ID,
        "business_unit_id": UNIT_ID,
        "transaction_type": "inflow",
        "amount": 1_000_000,
        "currency": "IDR",
        "category": "project_revenue",
        "description": "Termin pertama",
        "occurred_at": NOW.isoformat(),
        "source": "dashboard",
        "evidence": {"receipt": "R-1"},
    }
    value.update(changes)
    return value


def make_service():
    repository = InMemoryFinancialRepository()
    return CanonicalFinanceService(repository), repository


def test_create_is_idempotent_balanced_and_authoritatively_read_back():
    service, repository = make_service()

    created = service.create_transaction(payload(), actor=ACTOR)
    replay = service.create_transaction(payload(), actor=ACTOR)

    assert created["duplicate"] is False
    assert replay == {**created, "duplicate": True}
    assert UUID(created["transaction"]["id"])
    assert created["transaction"]["version"] == 1
    assert sum(posting["signed_amount"] for posting in created["transaction"]["postings"]) == 0
    assert {posting["account_class"] for posting in created["transaction"]["postings"]} == {"cash", "revenue"}
    assert repository.outbox_count == 1
    assert service.get_transaction(created["transaction"]["id"])["effective"]["id"] == created["transaction"]["id"]


def test_same_idempotency_key_with_different_payload_is_rejected():
    service, _ = make_service()
    service.create_transaction(payload(), actor=ACTOR)

    with pytest.raises(FinanceConflict, match="idempotency"):
        service.create_transaction(payload(amount=2_000_000), actor=ACTOR)


def test_correction_preserves_original_and_replaces_effective_state():
    service, _ = make_service()
    original = service.create_transaction(payload(), actor=ACTOR)["transaction"]

    corrected = service.correct_transaction(
        original["id"],
        {
            "idempotency_key": "txn-correct-0000001",
            "expected_version": 1,
            "amount": 1_250_000,
            "description": "Termin pertama terkoreksi",
            "reason": "Nilai bukti bank diperbarui",
        },
        actor=ACTOR,
    )["transaction"]
    view = service.get_transaction(original["id"])

    assert corrected["status"] == "correction"
    assert corrected["revision_of_id"] == original["id"]
    assert corrected["version"] == 2
    assert view["effective"]["id"] == corrected["id"]
    assert view["effective"]["amount"] == 1_250_000
    assert [item["id"] for item in view["history"]] == [original["id"], corrected["id"]]


def test_reversal_preserves_history_and_excludes_transaction_from_effective_list():
    service, _ = make_service()
    original = service.create_transaction(payload(), actor=ACTOR)["transaction"]

    reversed_result = service.reverse_transaction(
        original["id"],
        {
            "idempotency_key": "txn-reverse-0000001",
            "expected_version": 1,
            "reason": "Pembayaran dibatalkan bank",
        },
        actor=ACTOR,
    )["transaction"]
    view = service.get_transaction(original["id"])

    assert reversed_result["status"] == "reversal"
    assert reversed_result["reversal_of_id"] == original["id"]
    assert view["effective"] is None
    assert view["reversed"] is True
    assert service.list_effective_transactions() == []
    with pytest.raises(FinanceConflict, match="already reversed"):
        service.reverse_transaction(
            original["id"],
            {
                "idempotency_key": "txn-reverse-0000002",
                "expected_version": 2,
                "reason": "Tidak boleh dua kali",
            },
            actor=ACTOR,
        )


def test_optimistic_concurrency_allows_exactly_one_correction():
    service, _ = make_service()
    original = service.create_transaction(payload(), actor=ACTOR)["transaction"]

    def correct(index):
        return service.correct_transaction(
            original["id"],
            {
                "idempotency_key": f"txn-concurrent-{index:08d}",
                "expected_version": 1,
                "amount": 1_000_000 + index,
                "description": f"Koreksi {index}",
                "reason": "Uji optimistic concurrency",
            },
            actor=ACTOR,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(correct, index) for index in (1, 2)]
    successes = [future.result() for future in futures if future.exception() is None]
    failures = [future.exception() for future in futures if future.exception() is not None]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], FinanceConflict)
    assert "version" in str(failures[0])


@pytest.mark.parametrize(
    "changes, error",
    [
        ({"project_id": "Alpha"}, "project_id"),
        ({"amount": True}, "amount"),
        ({"currency": "USD"}, "currency"),
        ({"scope": "office"}, "project_id"),
        ({"unknown": "field"}, "unknown field"),
    ],
)
def test_create_validation_is_strict(changes, error):
    service, _ = make_service()

    with pytest.raises(FinanceValidationError, match=error):
        service.create_transaction(payload(**changes), actor=ACTOR)
