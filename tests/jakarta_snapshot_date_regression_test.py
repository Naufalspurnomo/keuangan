from datetime import datetime, timezone

from services.canonical_dashboard_snapshot import build_canonical_dashboard_snapshot
from tests.canonical_dashboard_snapshot_test import PROJECT, WALLET_A, WALLET_B, project, registry, transaction


def test_jakarta_midnight_month_boundary_dates_and_age():
    instant = '2026-10-31T17:00:00+00:00'
    row = transaction()
    row.update(occurred_at=instant, created_at=instant)
    proj = project()
    proj['start_date'] = '2026-10-31'
    debt = {'id': 'debt', 'status': 'open', 'principal': 10, 'outstanding': 10,
            'lender_wallet_id': WALLET_A, 'borrower_wallet_id': WALLET_B,
            'occurred_at': instant, 'due_at': '2026-11-30T17:00:00+00:00'}
    snapshot = build_canonical_dashboard_snapshot(transaction_chains=[[row]], projects=[proj],
                debts=[debt], registry=registry(), now=datetime(2026, 10, 31, 18, tzinfo=timezone.utc))
    assert snapshot['transactions'][0]['transaction_date'] == '2026-11-01'
    assert snapshot['cash_trend'][0]['month'] == '2026-11'
    assert snapshot['meta']['data_through'] == '2026-11-01'
    assert snapshot['meta']['as_of'] == '2026-10-31T18:00:00+00:00'
    assert snapshot['project_summaries'][0]['age_days'] == 1
    assert snapshot['project_summaries'][0]['first_activity_on'] == '2026-11-01'
    assert snapshot['debts'][0]['date'] == '2026-11-01'
    assert snapshot['debts'][0]['due_at'] == '2026-12-01'
