"""Offline regression: dashboard delegates to the same Sheets writers as chat."""
from datetime import date
from unittest.mock import patch

from services.dashboard_transaction_service import GoogleSheetsTransactionAdapter
from dashboard_api.write_contracts import TransactionRequest


def request(scope):
    return TransactionRequest(
        idempotency_key='integration-request-0001', date=date(2026, 11, 2),
        scope=scope, direction='Pengeluaran', amount=10000,
        description='Material pekerjaan', wallet='CV HB(101)', company='HOLLA',
        category='Gaji' if scope == 'office' else 'Material',
        project=None if scope == 'office' else 'Proyek Integrasi',
    )


def test_dashboard_project_uses_existing_sheets_writer():
    with patch('sheets_helper.append_project_transaction') as append:
        append.return_value = {'success': True}
        GoogleSheetsTransactionAdapter().append(
            request('project'), sender_name='Dashboard', source='Dashboard',
            message_id='dashboard:integration:project',
        )
    append.assert_called_once()
    assert append.call_args.kwargs['allow_queue'] is False
    assert append.call_args.kwargs['transaction_date'] == date(2026, 11, 2)


def test_dashboard_office_uses_existing_sheets_writer():
    with patch('sheets_helper.append_operational_transaction') as append:
        append.return_value = {'success': True}
        GoogleSheetsTransactionAdapter().append(
            request('office'), sender_name='Dashboard', source='Dashboard',
            message_id='dashboard:integration:office',
        )
    append.assert_called_once()
    assert append.call_args.kwargs['allow_queue'] is False
    assert append.call_args.kwargs['transaction_date'] == date(2026, 11, 2)
