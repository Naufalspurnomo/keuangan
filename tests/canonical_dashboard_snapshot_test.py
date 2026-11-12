from __future__ import annotations

from datetime import datetime, timezone

from services.canonical_dashboard_snapshot import build_canonical_dashboard_snapshot


NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
WALLET_A = "00000000-0000-4000-8000-000000000101"
WALLET_B = "00000000-0000-4000-8000-000000000102"
UNIT_A = "00000000-0000-4000-8000-000000000201"
UNIT_B = "00000000-0000-4000-8000-000000000202"
PROJECT = "00000000-0000-4000-8000-000000000301"
TX = "00000000-0000-4000-8000-000000000401"


def registry():
    return {
        "wallets": [
            {"id": WALLET_A, "display_name": "CV HB(101)"},
            {"id": WALLET_B, "display_name": "TX SBY(216)"},
        ],
        "business_units": [
            {"id": UNIT_A, "legal_name": "HOLLA"},
            {"id": UNIT_B, "legal_name": "TEXTURIN-Surabaya"},
        ],
        "opening_balances": [
            {
                "wallet_id": WALLET_A,
                "business_unit_id": UNIT_A,
                "amount": 1_000_000,
                "effective_at": "2026-11-01T00:00:00+00:00",
            }
        ],
        "balance_adjustments": [],
    }


def project():
    return {
        "id": PROJECT,
        "name": "Proyek Baru",
        "wallet": "CV HB(101)",
        "company": "HOLLA",
        "status": "active",
        "start_date": "2026-11-10",
        "completion_date": None,
        "created_at": "2026-11-10T00:00:00+00:00",
        "updated_at": "2026-11-10T00:00:00+00:00",
    }


def transaction(*, status="posted", evidence=None):
    return {
        "id": TX,
        "scope": "project",
        "project_id": PROJECT,
        "transaction_type": "inflow",
        "flow_class": "external",
        "amount": 250_000,
        "currency": "IDR",
        "category": "Termin",
        "description": "Pembayaran termin pertama",
        "occurred_at": "2026-11-12T02:00:00+00:00",
        "source": "dashboard",
        "source_reference": None,
        "evidence": evidence or {},
        "actor": {"id": "owner", "role": "boss", "channel": "dashboard"},
        "revision_of_id": None,
        "reversal_of_id": None,
        "version": 1,
        "status": status,
        "created_at": "2026-11-12T02:00:01+00:00",
        "postings": [
            {
                "id": "00000000-0000-4000-8000-000000000501",
                "wallet_id": WALLET_A,
                "business_unit_id": UNIT_A,
                "account_class": "cash",
                "signed_amount": 250_000,
                "currency": "IDR",
            },
            {
                "id": "00000000-0000-4000-8000-000000000502",
                "wallet_id": None,
                "business_unit_id": UNIT_A,
                "account_class": "revenue",
                "signed_amount": -250_000,
                "currency": "IDR",
            },
        ],
    }


def test_empty_canonical_database_is_a_valid_fresh_zero_snapshot():
    snapshot = build_canonical_dashboard_snapshot(
        transaction_chains=[],
        projects=[],
        debts=[],
        registry=registry(),
        now=NOW,
    )

    assert snapshot["meta"]["source"] == "Hollawall PostgreSQL canonical ledger"
    assert snapshot["meta"]["freshness"] == "fresh"
    assert snapshot["meta"]["data_through"] is None
    assert snapshot["overview"]["metrics"]["cash_balance"] == 1_000_000
    assert snapshot["overview"]["metrics"]["operating_inflow"] == 0
    assert snapshot["transactions"] == []
    assert snapshot["project_summaries"] == []


def test_snapshot_projects_effective_transaction_and_wallet_balance_from_same_ledger():
    snapshot = build_canonical_dashboard_snapshot(
        transaction_chains=[[transaction()]],
        projects=[project()],
        debts=[],
        registry=registry(),
        now=NOW,
    )

    assert snapshot["overview"]["metrics"]["cash_balance"] == 1_250_000
    assert snapshot["overview"]["metrics"]["operating_inflow"] == 250_000
    assert snapshot["transactions"][0]["canonical_transaction_id"] == TX
    assert snapshot["transactions"][0]["transaction_version"] == 1
    assert snapshot["transactions"][0]["project_id"] == PROJECT
    assert snapshot["transactions"][0]["wallet"] == "CV HB(101)"
    assert snapshot["transactions"][0]["company"] == "HOLLA"
    assert snapshot["project_summaries"][0]["project_id"] == PROJECT
    assert snapshot["project_summaries"][0]["lifecycle_status"] == "active"
    assert snapshot["project_summaries"][0]["net_cashflow"] == 250_000


def test_reversal_and_acceptance_test_are_excluded_from_business_snapshot():
    reversed_record = transaction(status="reversal")
    reversed_record["id"] = "00000000-0000-4000-8000-000000000402"
    reversed_record["reversal_of_id"] = TX
    reversed_record["version"] = 2
    acceptance = transaction(evidence={"is_acceptance_test": True})

    reversed_snapshot = build_canonical_dashboard_snapshot(
        transaction_chains=[[transaction(), reversed_record]],
        projects=[project()],
        debts=[],
        registry=registry(),
        now=NOW,
    )
    acceptance_snapshot = build_canonical_dashboard_snapshot(
        transaction_chains=[[acceptance]],
        projects=[project()],
        debts=[],
        registry=registry(),
        now=NOW,
    )

    assert reversed_snapshot["transactions"] == []
    assert acceptance_snapshot["transactions"] == []
    assert reversed_snapshot["overview"]["metrics"]["cash_balance"] == 1_000_000
    assert acceptance_snapshot["overview"]["metrics"]["cash_balance"] == 1_000_000


def test_debt_projection_exposes_principal_repaid_outstanding_without_inflating_operating_cashflow():
    debt = {
        "id": "00000000-0000-4000-8000-000000000601",
        "lender_wallet_id": WALLET_A,
        "borrower_wallet_id": WALLET_B,
        "project_id": PROJECT,
        "principal": 500_000,
        "repaid": 200_000,
        "outstanding": 300_000,
        "status": "open",
        "occurred_at": "2026-11-11T00:00:00+00:00",
        "description": "Dana talangan proyek",
    }
    snapshot = build_canonical_dashboard_snapshot(
        transaction_chains=[],
        projects=[project()],
        debts=[debt],
        registry=registry(),
        now=NOW,
    )

    assert snapshot["overview"]["metrics"]["open_internal_debt"] == 300_000
    assert snapshot["overview"]["metrics"]["operating_inflow"] == 0
    assert snapshot["overview"]["metrics"]["operating_outflow"] == 0
    assert snapshot["debts"][0]["amount"] == 500_000
    assert snapshot["debts"][0]["repaid"] == 200_000
    assert snapshot["debts"][0]["outstanding"] == 300_000
