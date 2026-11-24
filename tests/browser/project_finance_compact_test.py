"""Local project finance layout, with all network responses replaced by fixtures."""
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect
from tests.browser import dashboard_visual_acceptance_test as harness


class ProjectFinanceCompactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.DashboardVisualAcceptanceTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.DashboardVisualAcceptanceTests.tearDownClass.__func__(cls)

    new_page = harness.DashboardVisualAcceptanceTests.new_page

    def test_compact_project_finance_on_desktop_and_mobile(self):
        output = Path('artifacts/project-finance')
        output.mkdir(parents=True, exist_ok=True)
        project_id = harness.PROJECT_IDS['Surabaya Office']
        for width, height in ((1440, 900), (390, 844)):
            with self.subTest(width=width):
                context, page, errors = self.new_page(width, height)

                def documents(route):
                    action = parse_qs(urlparse(route.request.url).query).get('action', [''])[0]
                    if action == 'payment_summary':
                        data = {'project_id': project_id, 'contract_total': 100000000, 'invoiced_total': 40000000,
                                'unbilled_total': 60000000, 'paid_total': 30000000, 'contract_outstanding': 70000000,
                                'overpaid_total': 0, 'unapplied_total': 0, 'payment_status': 'PARTIALLY_PAID', 'invoices': []}
                    else:
                        data = {'items': []}
                    route.fulfill(json={'api_version': 'dashboard.v1', 'data': data, 'meta': {'capabilities': {'reads_enabled': True}}})

                context.route('**/admin/api/documents.php**', documents)
                context.route('**/admin/api/evidence.php**', lambda route: route.fulfill(json={'api_version': 'dashboard.v1', 'data': {'items': []}, 'meta': {}}))
                page.goto(self.base_url + '/admin/#projects?project=' + project_id + '&tab=overview')
                expect(page.get_by_role('heading', name='Ringkasan keuangan')).to_be_visible()
                expect(page.get_by_role('navigation', name='Bagian keuangan proyek')).to_be_visible()
                page.screenshot(path=str(output / f'summary-{width}.png'), full_page=True)
                page.get_by_role('button', name='Laba Rugi', exact=True).click()
                expect(page.get_by_role('heading', name='Laba Rugi · perkiraan sementara')).to_be_visible()
                page.screenshot(path=str(output / f'profit-{width}.png'), full_page=True)
                page.get_by_role('navigation', name='Bagian keuangan proyek').get_by_role('button', name='Arus Kas', exact=True).click()
                expect(page.get_by_role('heading', name='Arus Kas', exact=True)).to_be_visible()
                overflow = page.evaluate('''() => [...document.querySelectorAll('body *')].filter(e => {
                    const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 2 && getComputedStyle(e).position !== 'fixed';
                }).map(e => ({tag:e.tagName, className:String(e.className), width:e.getBoundingClientRect().width, right:e.getBoundingClientRect().right})).slice(0, 25)''')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1, str(overflow))
                self.assertEqual(errors, [])
                context.close()

    def test_cashflow_filters_by_project_identity(self):
        context, page, errors = self.new_page(1440, 900)
        page.goto(self.base_url + '/admin/#cashflow')
        selector = page.get_by_label('Filter Project arus kas')
        expect(selector).to_be_visible()
        selector.select_option(harness.PROJECT_IDS['Surabaya Office'])
        ledger = page.locator('.ops-ledger-section')
        expect(ledger.get_by_text('Termin pekerjaan utama')).to_be_visible()
        expect(ledger.get_by_text('Material dan vendor')).to_have_count(0)
        self.assertEqual(errors, [])
        context.close()

    def test_owner_can_review_an_expense_and_see_the_estimate(self):
        context, page, errors = self.new_page(1440, 900)
        project_id = harness.PROJECT_IDS['Surabaya Office']
        capabilities = {'reads_enabled': True, 'project_document_writes_enabled': True}
        reviews = []

        def projects(route):
            action = parse_qs(urlparse(route.request.url).query).get('action', [''])[0]
            data = next(row for row in harness.PROJECT_RECORDS if row['id'] == project_id) if action == 'get' else {'items': harness.PROJECT_RECORDS}
            route.fulfill(json={'api_version': 'dashboard.v1', 'data': data, 'meta': {'capabilities': capabilities}})

        def documents(route):
            action = parse_qs(urlparse(route.request.url).query).get('action', [''])[0]
            if route.request.method == 'POST':
                body = route.request.post_data_json
                assert body['action'] == 'classify_expense'
                reviews[:] = [{'source_key': body['source_key'], 'classification': body['classification'], **body['expected_source']}]
                data = reviews[0]
            elif action == 'payment_summary':
                data = {'project_id': project_id, 'contract_total': 100000000, 'invoiced_total': 0, 'unbilled_total': 100000000,
                        'paid_total': 0, 'contract_outstanding': 100000000, 'overpaid_total': 0, 'unapplied_total': 0,
                        'payment_status': 'UNPAID', 'invoices': []}
            else:
                data = {'items': reviews if action == 'expense_classifications' else []}
            route.fulfill(json={'api_version': 'dashboard.v1', 'data': data, 'meta': {'capabilities': capabilities}})

        context.route('**/admin/api/projects.php**', projects)
        context.route('**/admin/api/write-session.php', lambda route: route.fulfill(json={
            'api_version': 'dashboard.v1', 'data': {'csrf_token': 'acceptance-csrf-token-0001', 'capabilities': {'writes_enabled': True, **capabilities}},
            'meta': {'capabilities': capabilities},
        }))
        context.route('**/admin/api/documents.php**', documents)
        context.route('**/admin/api/evidence.php**', lambda route: route.fulfill(json={'api_version': 'dashboard.v1', 'data': {'items': []}, 'meta': {'capabilities': capabilities}}))
        page.goto(self.base_url + '/admin/#projects?project=' + project_id + '&tab=overview')
        page.get_by_role('navigation', name='Bagian keuangan proyek').get_by_role('button', name='Laba Rugi').click()
        page.get_by_role('button', name='Tandai Operasional lapangan sebagai biaya proyek').click()
        expect(page.get_by_text('Biaya proyek', exact=False).first).to_be_visible()
        page.get_by_role('navigation', name='Bagian keuangan proyek').get_by_role('button', name='Ringkasan').click()
        expect(page.get_by_role('region', name='Ringkasan kas Surabaya Office').get_by_text('Rp 73.250.000')).to_be_visible()
        self.assertEqual(reviews[0]['classification'], 'project_cost')
        self.assertEqual(errors, [])
        context.close()
