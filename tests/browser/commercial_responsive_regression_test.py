"""Local-only commercial editor geometry; all API calls intercepted fixtures."""
import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import expect
from tests.browser import dashboard_visual_acceptance_test as harness

EVIDENCE = Path(__file__).resolve().parents[2] / 'artifacts/commercial-responsive'

class CommercialResponsiveTests(unittest.TestCase):
    base_url: str

    @classmethod
    def setUpClass(cls):
        harness.DashboardVisualAcceptanceTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.DashboardVisualAcceptanceTests.tearDownClass.__func__(cls)

    new_page = harness.DashboardVisualAcceptanceTests.new_page

    def test_commercial_editors_across_breakpoints(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        measurements = []
        for width, height in ((320, 720), (390, 844), (844, 390), (768, 1024), (1024, 768), (1440, 1000)):
            with self.subTest(width=width, height=height):
                context, page, errors = self.new_page(width, height)
                def projects(route):
                    data = harness.PROJECT_RECORDS[0] if 'action=get' in route.request.url else {'items': harness.PROJECT_RECORDS}
                    route.fulfill(json={'api_version':'dashboard.v1', 'data':data, 'meta':{'capabilities':{'reads_enabled':True,'project_document_writes_enabled':True}}})
                context.route('**/admin/api/projects.php**', projects)
                context.route('**/admin/api/write-session.php', lambda r: r.fulfill(json={'api_version':'dashboard.v1','data':{'csrf_token':'acceptance-csrf-token-0001','capabilities':{'writes_enabled':True,'project_document_writes_enabled':True}},'meta':{'capabilities':{'project_document_writes_enabled':True}}}))
                def documents(route):
                    action = parse_qs(urlparse(route.request.url).query).get('action',[''])[0]
                    data = {'items':[]}
                    if action == 'payment_summary':
                        data = {'project_id':harness.PROJECT_IDS['Surabaya Office'],'payment_status':'NOT_CONTRACTED','contract_amount':0,'invoiced_amount':0,'received_amount':0,'outstanding_amount':0,'invoices':[]}
                    route.fulfill(json={'api_version':'dashboard.v1','data':data,'meta':{'capabilities':{'project_document_writes_enabled':True}}})
                context.route('**/admin/api/documents.php**', documents)
                page.goto(self.base_url + '/admin/#projects?project=' + harness.PROJECT_IDS['Surabaya Office'] + '&tab=documents&document=new&type=invoice')
                page.wait_for_load_state('networkidle')
                page.get_by_role('button',name='Buat invoice',exact=True).click()
                expect(page.get_by_role('heading',name='Buat invoice',exact=True)).to_be_visible()
                page.get_by_label('Deskripsi item 1',exact=True).fill('Panel akustik penerimaan visual')
                page.get_by_label('Luas tagihan item 1 (m²)',exact=True).fill('25')
                page.get_by_label('PPM item 1', exact=True).fill('100000')
                if width <= 1120:
                    page.get_by_role('tab', name='Pratinjau').click()
                preview = page.get_by_role('article', name='Pratinjau A4 Invoice Texturin Surabaya')
                expect(preview).to_be_visible()
                bounds = preview.evaluate('''el => {
                    const page=el.getBoundingClientRect(), meta=el.querySelector('.live-meta-right').getBoundingClientRect(), left=el.querySelector('.live-meta-left').getBoundingClientRect();
                    const lines=el.querySelector('.live-lines').getBoundingClientRect(), totals=el.querySelector('.live-totals').getBoundingClientRect();
                    return {metaBottom: (meta.bottom-page.top)/page.height, leftBottom: (left.bottom-page.top)/page.height, linesBottom: lines.bottom, totalsTop: totals.top};
                }''')
                self.assertLess(bounds['metaBottom'], .235)
                self.assertLess(bounds['leftBottom'], .235)
                self.assertLessEqual(bounds['linesBottom'], bounds['totalsTop'] + 1)
                page.screenshot(path=str(EVIDENCE / f'invoice-{width}x{height}.png'),full_page=True)
                geometry = page.evaluate('''() => ({width:innerWidth, height:innerHeight, scroll:document.documentElement.scrollWidth, offenders:[...document.querySelectorAll('.document-workspace input,.document-workspace textarea,.document-workspace button')].filter(e=>{const r=e.getBoundingClientRect();return r.width && (r.right>innerWidth+1||r.left< -1)}).map(e=>({tag:e.tagName,label:e.getAttribute('aria-label'),right:e.getBoundingClientRect().right}))})''')
                measurements.append(geometry)
                self.assertEqual(geometry['offenders'], [], str(geometry))
                self.assertLessEqual(geometry['scroll'],width+1,str(geometry))
                page.get_by_role('button',name='Tutup',exact=True).click() if page.get_by_role('button',name='Tutup',exact=True).count() else page.goto(self.base_url + '/admin/#projects?project=' + harness.PROJECT_IDS['Surabaya Office'] + '&tab=documents')
                page.get_by_role('button',name='Buat quotation',exact=True).click()
                page.screenshot(path=str(EVIDENCE / f'quotation-{width}x{height}.png'),full_page=True)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width+1)
                quotation_offenders = page.evaluate('''() => [...document.querySelectorAll('.quotation-editor input,.quotation-editor textarea,.quotation-editor select,.quotation-editor button')].filter(e=>{const r=e.getBoundingClientRect();return r.width && (r.right>innerWidth+1||r.left< -1)}).map(e=>({tag:e.tagName,label:e.getAttribute('aria-label'),right:e.getBoundingClientRect().right}))''')
                self.assertEqual(quotation_offenders, [], str(quotation_offenders))
                self.assertEqual(errors, [], str(errors))
                context.close()
        (EVIDENCE / 'geometry.json').write_text(json.dumps(measurements,indent=2))
