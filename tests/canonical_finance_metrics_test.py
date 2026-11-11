from __future__ import annotations

from pathlib import Path

from services.canonical_finance_metrics import METRIC_ORACLE_VERSION, calculate_metrics


ROOT = Path(__file__).resolve().parents[1]


CUTOFF = "2026-11-11T12:00:00+00:00"


def posting(account_class, amount, *, wallet_id=None, business_unit_id=None):
    return {
        "account_class": account_class,
        "signed_amount": amount,
        "wallet_id": wallet_id,
        "business_unit_id": business_unit_id,
        "currency": "IDR",
    }


def transaction(
    transaction_id,
    *,
    occurred_at="2026-11-10T10:00:00+00:00",
    project_id=None,
    scope="group",
    status="posted",
    evidence=None,
    postings=(),
):
    return {
        "id": transaction_id,
        "occurred_at": occurred_at,
        "project_id": project_id,
        "scope": scope,
        "status": status,
        "evidence": evidence or {},
        "postings": list(postings),
    }


def test_metric_oracle_v1_applies_cutoff_exclusions_and_exact_integer_formulas():
    chains = [
        [
            transaction(
                "sale-v1",
                project_id="project-a",
                scope="project",
                postings=[posting("cash", 1_000_000, wallet_id="wallet-a", business_unit_id="unit-a"), posting("revenue", -1_000_000)],
            ),
            transaction(
                "sale-v2",
                project_id="project-a",
                scope="project",
                status="correction",
                postings=[posting("cash", 1_200_000, wallet_id="wallet-a", business_unit_id="unit-a"), posting("revenue", -1_200_000)],
            ),
        ],
        [
            transaction(
                "cost-v1",
                project_id="project-a",
                scope="project",
                postings=[posting("cash", -300_000, wallet_id="wallet-a", business_unit_id="unit-a"), posting("expense", 300_000)],
            )
        ],
        [
            transaction("reversed-v1", postings=[posting("cash", 99_000, wallet_id="wallet-a"), posting("revenue", -99_000)]),
            transaction("reversed-v2", status="reversal", postings=[posting("cash", -99_000, wallet_id="wallet-a"), posting("revenue", 99_000)]),
        ],
        [transaction("quarantine", evidence={"quarantined": True}, postings=[posting("cash", 9_000, wallet_id="wallet-a"), posting("revenue", -9_000)])],
        [transaction("review", evidence={"review_status": "pending"}, postings=[posting("cash", 8_000, wallet_id="wallet-a"), posting("revenue", -8_000)])],
        [transaction("acceptance", evidence={"is_acceptance_test": True}, postings=[posting("cash", 7_000, wallet_id="wallet-a"), posting("revenue", -7_000)])],
        [transaction("future", occurred_at="2026-11-11T12:00:00.000001+00:00", postings=[posting("cash", 6_000, wallet_id="wallet-a"), posting("revenue", -6_000)])],
    ]

    result = calculate_metrics(
        cutoff=CUTOFF,
        transaction_chains=chains,
        opening_balances=[
            {"wallet_id": "wallet-a", "business_unit_id": "unit-a", "amount": 50_000, "effective_at": "2025-01-01T00:00:00+00:00"},
            {"wallet_id": "wallet-a", "business_unit_id": "unit-a", "amount": 100_000, "effective_at": "2026-01-01T00:00:00+00:00"},
        ],
        balance_adjustments=[{"wallet_id": "wallet-a", "business_unit_id": "unit-a", "delta_amount": 50_000, "effective_at": CUTOFF}],
        debt_projections=[{
            "id": "debt-a",
            "lender_wallet_id": "wallet-a",
            "borrower_wallet_id": "wallet-b",
            "lender_business_unit_id": "unit-a",
            "borrower_business_unit_id": "unit-b",
            "outstanding": 400_000,
            "due_at": "2026-10-01T00:00:00+00:00",
            "status": "open",
        }],
        monthly_operating_outflow=300_000,
    )

    assert result["oracle_version"] == METRIC_ORACLE_VERSION == "canonical.finance.metrics.v1"
    assert result["cutoff"] == CUTOFF
    assert result["excluded"] == {"acceptance_test": 1, "after_cutoff": 1, "quarantine": 1, "reversed": 1, "review": 1}
    assert result["group"] == {"external_inflow": 1_200_000, "external_outflow": 300_000, "net_cashflow": 900_000}
    assert result["wallets"]["wallet-a"] == {
        "opening_balance": 100_000,
        "cash_balance": 1_000_000,
        "adjustments": 50_000,
        "available_balance": 1_050_000,
        "receivable": 400_000,
        "payable": 0,
        "adjusted_balance": 1_450_000,
        "runway_months_basis_points": 35_000,
        "health": "Healthy",
    }
    assert result["wallets"]["wallet-b"]["payable"] == 400_000
    assert result["projects"]["project-a"] == {
        "revenue": 1_200_000,
        "cost": 300_000,
        "cashflow": 900_000,
        "gross_profit": 900_000,
        "margin_basis_points": 7_500,
        "contribution": 900_000,
    }
    assert result["debt_aging"] == {"current": 0, "days_1_30": 0, "days_31_60": 400_000, "days_61_90": 0, "days_over_90": 0}


def test_metric_oracle_cutoff_is_inclusive_and_health_thresholds_are_deterministic():
    result = calculate_metrics(
        cutoff=CUTOFF,
        transaction_chains=[[transaction("at-cutoff", occurred_at=CUTOFF, postings=[posting("cash", 100, wallet_id="watch"), posting("revenue", -100)])]],
        opening_balances=[{"wallet_id": "critical", "business_unit_id": "unit-c", "amount": -1, "effective_at": CUTOFF}],
        balance_adjustments=[],
        debt_projections=[],
        monthly_operating_outflow=100,
    )

    assert result["wallets"]["watch"]["health"] == "Watch"
    assert result["wallets"]["critical"]["health"] == "Critical"
    assert result["group"]["external_inflow"] == 100


def test_metric_oracle_treats_open_debt_without_due_date_as_current():
    result = calculate_metrics(
        cutoff=CUTOFF,
        transaction_chains=[],
        opening_balances=[],
        balance_adjustments=[],
        debt_projections=[{
            "id": "debt-undated",
            "lender_wallet_id": "wallet-a",
            "borrower_wallet_id": "wallet-b",
            "outstanding": 10_000,
            "due_at": None,
            "status": "open",
        }],
        monthly_operating_outflow=0,
    )

    assert result["debt_aging"]["current"] == 10_000


def test_sql_and_documentation_are_versioned_with_the_service_oracle():
    sql = (ROOT / "dashboard_api" / "queries" / "canonical_finance_metrics_v1.sql").read_text()
    documentation = (ROOT / "docs" / "finance" / "CANONICAL_METRICS.md").read_text()

    assert sql.startswith(f"-- {METRIC_ORACLE_VERSION}")
    assert "$1::timestamptz" in sql
    assert "is_acceptance_test" in sql
    assert "review_status" in sql
    assert "status <> 'reversal'" in sql
    assert "flow_class <> 'internal'" in sql
    assert "latest_opening_per_unit" in sql
    assert "debt_aging" in sql
    assert METRIC_ORACLE_VERSION in documentation
    assert "013_interwallet_debt_event_contract" in documentation
    assert "Google Sheets remains a protected derived export" in documentation


def test_metric_oracle_rejects_non_integer_money_and_unbalanced_effective_transactions():
    invalid_money = [[transaction("bad-money", postings=[posting("cash", 1.5, wallet_id="wallet-a"), posting("revenue", -1.5)])]]
    try:
        calculate_metrics(cutoff=CUTOFF, transaction_chains=invalid_money, opening_balances=[], balance_adjustments=[], debt_projections=[], monthly_operating_outflow=1)
    except ValueError as error:
        assert "integer" in str(error)
    else:
        raise AssertionError("non-integer IDR must fail")

    unbalanced = [[transaction("unbalanced", postings=[posting("cash", 100, wallet_id="wallet-a"), posting("revenue", -99)])]]
    try:
        calculate_metrics(cutoff=CUTOFF, transaction_chains=unbalanced, opening_balances=[], balance_adjustments=[], debt_projections=[], monthly_operating_outflow=1)
    except ValueError as error:
        assert "balanced" in str(error)
    else:
        raise AssertionError("unbalanced transaction must fail")
