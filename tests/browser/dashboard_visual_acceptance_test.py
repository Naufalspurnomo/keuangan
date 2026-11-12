import contextlib
import functools
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import threading
import unittest

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dashboard" / "dist"
ARTIFACTS = ROOT / "artifacts" / "dashboard-v1"

META = {
    "as_of": "2026-10-21T12:00:00Z",
    "freshness": "fresh",
    "data_completeness": {"valid_rows": 148, "invalid_rows": 2, "completeness_pct": 98.7},
}
OVERVIEW = {
    "metrics": {
        "cash_balance": 868_900_000,
        "operating_inflow": 497_500_000,
        "operating_outflow": 192_150_000,
        "net_operating_cashflow": 305_350_000,
        "open_internal_debt": 28_500_000,
        "project_cashflow": 305_350_000,
    },
    "counts": {"valid_rows": 148, "invalid_rows": 2},
    "labels": {
        "cash_balance": "Saldo kas",
        "operating_inflow": "Pemasukan operasional",
        "operating_outflow": "Pengeluaran operasional",
        "net_operating_cashflow": "Arus kas operasional bersih",
        "open_internal_debt": "Hutang antar-dompet terbuka",
        "project_cashflow": "Arus kas proyek bersih",
    },
    "drilldowns": {},
}
PROJECT_IDS = {
    "Surabaya Office": "00000000-0000-4000-8000-000000000001",
    "Grand Galaxy": "00000000-0000-4000-8000-000000000002",
    "Mawar Residence": "00000000-0000-4000-8000-000000000003",
    "Texturin Sisipan": "00000000-0000-4000-8000-000000000004",
    "Proyek Selesai": "00000000-0000-4000-8000-000000000005",
}
PROJECT_RECORDS = [
    {
        "id": project_id,
        "name": name,
        "client_name": f"Klien {name}",
        "client_company": "",
        "client_address": "",
        "client_contact": "",
        "issuer_key": "hollawall",
        "wallet": "TX SBY(216)" if name != "Texturin Sisipan" else "TX BALI(087)",
        "company": "TEXTURIN-Surabaya" if name != "Texturin Sisipan" else "TEXTURIN-Bali",
        "status": "completed" if name == "Proyek Selesai" else "active",
        "start_date": "2024-01-01" if name == "Proyek Selesai" else "2026-01-01",
        "completion_date": "2026-05-02" if name == "Proyek Selesai" else None,
        "contract_notes": "",
        "lock_version": 1,
        "archived_at": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-10-21T12:00:00Z",
    }
    for name, project_id in PROJECT_IDS.items()
]


def route_projects(route):
    capabilities = {
        "reads_enabled": True,
        "project_document_writes_enabled": False,
        "transaction_correction_reversal": False,
        "hard_delete": False,
    }
    url = route.request.url
    if "action=get" in url:
        project_id = url.split("project_id=", 1)[1].split("&", 1)[0]
        item = next((project for project in PROJECT_RECORDS if project["id"] == project_id), None)
        if item is None:
            route.fulfill(status=404, content_type="application/json", body=json.dumps({"api_version": "dashboard.v1", "error": {"code": "not_found"}}))
            return
        data = item
    else:
        data = {"items": PROJECT_RECORDS}
    route.fulfill(status=200, content_type="application/json", body=json.dumps({
        "api_version": "dashboard.v1",
        "data": data,
        "meta": {"capabilities": capabilities},
    }))

TRANSACTIONS = [
    {"id": 1, "transaction_date": "2026-10-21", "transaction_type": "Pemasukan", "amount": 125_000_000, "wallet": "TX SBY(216)", "company": "Hollawall", "project": "Surabaya Office", "notes": "Termin pekerjaan utama"},
    {"id": 2, "transaction_date": "2026-10-20", "transaction_type": "Pengeluaran", "amount": 18_400_000, "wallet": "BCA(056)", "company": "Hollawall", "project": "Grand Galaxy", "notes": "Material dan vendor"},
    {"id": 3, "transaction_date": "2026-10-19", "transaction_type": "Pemasukan", "amount": 87_500_000, "wallet": "KPR BRI(031)", "company": "Hollawall", "project": "Mawar Residence", "notes": "Pembayaran progres"},
    {"id": 4, "transaction_date": "2026-10-18", "transaction_type": "Pengeluaran", "amount": 26_750_000, "wallet": "TX SBY(216)", "company": "Hollawall", "project": "Surabaya Office", "notes": "Operasional lapangan"},
    {"id": 5, "transaction_date": "2026-10-17", "transaction_type": "Pemasukan", "amount": 70_000_000, "wallet": "BCA(056)", "company": "Hollawall", "project": "Grand Galaxy", "notes": "Termin kedua"},
    {"id": 6, "transaction_date": "2026-10-16", "transaction_type": "Pengeluaran", "amount": 35_400_000, "wallet": "KPR BRI(031)", "company": "Hollawall", "project": "Mawar Residence", "notes": "Pembelian material"},
    {"id": 9, "source_key": "CV HB(101):project:completed", "transaction_date": "2026-05-02", "transaction_type": "Pemasukan", "amount": 12_500_000, "wallet": "CV HB(101)", "company": "HOLLA", "project": "Proyek Selesai", "notes": "Pelunasan proyek", "scope": "project"},
    *[
        {"id": 100 + index, "source_key": f"CV HB(101):acceptance:{100 + index}", "transaction_date": f"2026-10-{15 - index:02d}", "transaction_type": "Pemasukan" if index % 3 == 0 else "Pengeluaran", "amount": 1_000_000 + index * 125_000, "wallet": "CV HB(101)", "company": "Hollawall", "project": f"Audit Wallet {index + 1}", "notes": f"Mutasi acceptance {index + 1}", "internal_movement": index == 1, "transfer_scope": "internal" if index == 1 else "external"}
        for index in range(10)
    ],
]
TRANSACTIONS = [
    {
        **row,
        **(
            {"project_id": PROJECT_IDS[row["project"]], "scope": "project"}
            if row.get("project") in PROJECT_IDS
            else {"project": None, "scope": "office"}
        ),
    }
    for row in TRANSACTIONS
]


SNAPSHOT = {
    "version": "dashboard.snapshot.v1",
    "meta": {**META, "data_through": "2026-10-21", "source": "acceptance fixture"},
    "overview": OVERVIEW,
    "wallets": [
        {"source_key": "CV HB(101):wallet:summary", "name": "CV HB(101)", "balance": 300_000_000},
        {"source_key": "TX SBY(216):wallet:summary", "name": "TX SBY(216)", "balance": 318_900_000},
        {"source_key": "TX Bali(087):wallet:summary", "name": "TX Bali(087)", "balance": 250_000_000},
        {"source_key": "BCA(056):wallet:summary", "name": "BCA(056)", "balance": 40_000_000},
        {"source_key": "BRI(031):wallet:summary", "name": "BRI(031)", "balance": 30_000_000},
        {"source_key": "CASH:wallet:summary", "name": "Kas Operasional", "balance": 20_000_000},
        {"source_key": "PETTY:wallet:summary", "name": "Kas Kecil", "balance": 10_000_000},
    ],
    "transactions": TRANSACTIONS,
    "debts": [{"source_key": "HUTANG:2", "date": "2026-10-20", "amount": 28_500_000, "notes": "Bridge", "borrower": "CV HB(101)", "lender": "TX SBY(216)", "status": "OPEN"}],
    "cash_trend": [
        {"month": "2026-08", "balance": 220_000_000, "net_movement": 220_000_000},
        {"month": "2026-09", "balance": 485_000_000, "net_movement": 265_000_000},
        {"month": "2026-10", "balance": 790_350_000, "net_movement": 305_350_000},
    ],
    "project_summaries": [
        {"name": "Surabaya Office", "portfolio": "Hollawall", "net_cashflow": 98_250_000, "age_days": 4, "health": "healthy", "lifecycle_status": "active", "started_on": "2026-10-17", "first_activity_on": "2026-10-17", "transaction_count": 12, "last_activity_on": "2026-10-21"},
        {"name": "Grand Galaxy", "portfolio": "Hollawall", "net_cashflow": 70_400_000, "age_days": 10, "health": "healthy", "lifecycle_status": "active", "started_on": "2026-10-11", "first_activity_on": "2026-10-12", "transaction_count": 14, "last_activity_on": "2026-10-20"},
        {"name": "Mawar Residence", "portfolio": "Hollawall", "net_cashflow": 52_100_000, "age_days": 21, "health": "watch", "lifecycle_status": "active", "started_on": "2026-09-30", "first_activity_on": "2026-10-01", "transaction_count": 19, "last_activity_on": "2026-10-19"},
        {"name": "Texturin Sisipan", "portfolio": "Texturin", "net_cashflow": 31_900_000, "age_days": 45, "health": "overdue", "lifecycle_status": "active", "started_on": "2026-09-06", "first_activity_on": "2026-09-08", "transaction_count": 21, "last_activity_on": "2026-10-18"},
        {"name": "Proyek Selesai", "portfolio": "Hollawall", "net_cashflow": 12_500_000, "age_days": 999, "health": "completed", "lifecycle_status": "completed", "started_on": "2024-01-01", "completed_on": "2026-05-02", "transaction_count": 9, "last_activity_on": "2026-05-02", "source_key_first": "CV HB(101):project:completed"}
    ],
}
SNAPSHOT["project_summaries"] = [
    {**project, "project_id": PROJECT_IDS[project["name"]]}
    for project in SNAPSHOT["project_summaries"]
]


UPDATED_SNAPSHOT = json.loads(json.dumps(SNAPSHOT))
UPDATED_SNAPSHOT["overview"]["metrics"]["operating_inflow"] += 40_000_000
UPDATED_SNAPSHOT["overview"]["metrics"]["operating_outflow"] += 5_000_000
UPDATED_SNAPSHOT["overview"]["metrics"]["net_operating_cashflow"] += 35_000_000
UPDATED_SNAPSHOT["overview"]["counts"]["valid_rows"] += 2
UPDATED_SNAPSHOT["meta"]["as_of"] = "2026-10-22T08:10:00Z"
UPDATED_SNAPSHOT["meta"]["data_through"] = "2026-10-22"
UPDATED_SNAPSHOT["transactions"] = [
    {"id": 7, "transaction_date": "2026-10-22", "transaction_type": "Pemasukan", "amount": 40_000_000, "wallet": "TX SBY(216)", "company": "Hollawall", "project": "Surabaya Office", "project_id": PROJECT_IDS["Surabaya Office"], "scope": "project", "notes": "Termin baru proyek", "internal_movement": False, "transfer_scope": "external", "source_key": "TX SBY(216):pemasukan:217"},
    {"id": 8, "transaction_date": "2026-10-22", "transaction_type": "Pengeluaran", "amount": 5_000_000, "wallet": "TX SBY(216)", "company": "Hollawall", "project": "Surabaya Office", "project_id": PROJECT_IDS["Surabaya Office"], "scope": "project", "notes": "Reversal termin salah", "internal_movement": False, "transfer_scope": "external", "source_key": "TX SBY(216):pengeluaran:218"},
    *UPDATED_SNAPSHOT["transactions"],
]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith('/admin/'):
            self.path = self.path.removeprefix('/admin')
        super().do_GET()

    def log_message(self, format, *args):  # noqa: A002
        return


@contextlib.contextmanager
def serve(directory: Path):
    handler = functools.partial(QuietHandler, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            worker.join(timeout=5)


class DashboardVisualAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (DIST / "index.html").is_file():
            raise RuntimeError("dashboard build missing; run npm run build")
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        cls.server_context = serve(DIST)
        cls.base_url = cls.server_context.__enter__()
        cls.playwright = sync_playwright().start()
        executable = os.environ.get("CHROMIUM_PATH") or shutil.which("google-chrome") or shutil.which("chromium") or "/snap/bin/chromium"
        cls.browser = cls.playwright.chromium.launch(
            headless=True,
            executable_path=executable,
            args=["--no-sandbox"],
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server_context.__exit__(None, None, None)

    def new_page(self, width, height, theme="light"):
        context = self.browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme)
        context.add_init_script(f"localStorage.setItem('hollawall-theme', '{theme}')")

        def route_api(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(SNAPSHOT))

        context.route("**/admin/api/snapshot.php", route_api)
        context.route("**/admin/api/projects.php**", route_projects)
        context.route(
            "**/admin/api/write-session.php",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "api_version": "dashboard.v1",
                    "data": {
                        "csrf_token": "acceptance-csrf-token-0001",
                        "capabilities": {"writes_enabled": False},
                    },
                }),
            ),
        )
        context.route(
            "**/admin/api/presensi.php**",
            lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"version": "presensi.admin.v1", "records": []})),
        )
        context.route(
            "**/admin/api/inbox-reviews.php**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "api_version": "dashboard.v1",
                    "data": {"items": [], "writes_enabled": False, "allowed_actions": []},
                }),
            ),
        )
        context.route("**/favicon.ico", lambda route: route.fulfill(status=204, body=""))
        page = context.new_page()
        console_errors = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" and "Failed to load resource" not in message.text else None)
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: console_errors.append(f"request:{request.method}:{request.url}:{request.failure}")
            if not (request.method == "GET" and request.url.endswith("/admin/api/snapshot.php") and "ERR_ABORTED" in str(request.failure))
            else None,
        )
        page.on("response", lambda response: console_errors.append(f"response:{response.status}:{response.url}") if response.status >= 400 else None)
        return context, page, console_errors

    def new_dynamic_page(self, width, height, theme="light"):
        context = self.browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme)
        context.add_init_script(f"localStorage.setItem('hollawall-theme', '{theme}')")
        page = context.new_page()
        page.clock.install()
        console_errors = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" and "Failed to load resource" not in message.text else None)
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: console_errors.append(f"request:{request.method}:{request.url}:{request.failure}")
            if not (request.method == "GET" and request.url.endswith("/admin/api/snapshot.php") and "ERR_ABORTED" in str(request.failure))
            else None,
        )
        page.on("response", lambda response: console_errors.append(f"response:{response.status}:{response.url}") if response.status >= 400 else None)
        state = {"calls": 0}

        def route_api(route):
            state["calls"] += 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps(SNAPSHOT if state["calls"] == 1 else UPDATED_SNAPSHOT))

        context.route("**/admin/api/snapshot.php", route_api)
        context.route("**/admin/api/projects.php**", route_projects)
        context.route(
            "**/admin/api/write-session.php",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "api_version": "dashboard.v1",
                    "data": {
                        "csrf_token": "acceptance-csrf-token-0001",
                        "capabilities": {"writes_enabled": False},
                    },
                }),
            ),
        )
        context.route(
            "**/admin/api/presensi.php**",
            lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"version": "presensi.admin.v1", "records": []})),
        )
        context.route(
            "**/admin/api/inbox-reviews.php**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "api_version": "dashboard.v1",
                    "data": {"items": [], "writes_enabled": False, "allowed_actions": []},
                }),
            ),
        )
        context.route("**/favicon.ico", lambda route: route.fulfill(status=204, body=""))
        return context, page, console_errors, state

    def assert_clean_render(self, page, errors):
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=90_000)
        page.get_by_role("heading", name="Pusat kendali keuangan Hollawall", exact=True).wait_for()
        page.locator(".recharts-responsive-container, .business-empty").first.wait_for()
        self.assertEqual(errors, [])
        metrics = page.evaluate("""() => ({
          viewport: document.documentElement.clientWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          theme: document.documentElement.dataset.theme,
          chartCount: document.querySelectorAll('.recharts-responsive-container').length,
          chartEmptyCount: document.querySelectorAll('.business-empty').length,
          visibleButtons: [...document.querySelectorAll('button')].filter(el => el.offsetParent !== null).length,
          unitNavigator: document.querySelectorAll('.unit-navigator').length,
          unitCanvas: document.querySelectorAll('.unit-focus-canvas').length,
          activityStream: document.querySelectorAll('.activity-stream').length,
          legacyCards: ['.portfolio-section', '.business-chart-card', '.business-ledger-card', '.overview-grid', '.activity-panel']
            .reduce((total, selector) => total + document.querySelectorAll(selector).length, 0),
          desktopTimeline: document.querySelectorAll('.vertical-timeline-shell').length,
          mobileProjectLists: document.querySelectorAll('.mobile-project-list').length,
          mobileTargets: [...document.querySelectorAll('.business-mode-switch button, .mobile-project-list button, .project-lane-navigation button, .sidebar nav button')]
            .map(el => el.getBoundingClientRect().height)
        })""")
        self.assertLessEqual(metrics["document"], metrics["viewport"])
        self.assertLessEqual(metrics["body"], metrics["viewport"])
        self.assertGreaterEqual(metrics["chartCount"] + metrics["chartEmptyCount"], 1)
        self.assertEqual(metrics["unitNavigator"], 1)
        self.assertEqual(metrics["unitCanvas"], 1)
        self.assertEqual(metrics["activityStream"], 1)
        self.assertEqual(metrics["legacyCards"], 0)
        if metrics["viewport"] <= 580:
            self.assertEqual(metrics["desktopTimeline"], 0)
            self.assertEqual(metrics["mobileProjectLists"], 2)
            self.assertGreaterEqual(min(metrics["mobileTargets"]), 44)
        else:
            self.assertEqual(metrics["desktopTimeline"], 2)
        self.assertGreater(metrics["visibleButtons"], 8)
        return metrics

    def test_desktop_light_and_dark(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                context, page, errors = self.new_page(1440, 1000, theme)
                metrics = self.assert_clean_render(page, errors)
                self.assertEqual(metrics["theme"], theme)
                page.screenshot(path=str(ARTIFACTS / f"desktop-{theme}-1440x1000.png"), full_page=True, timeout=90_000)
                context.close()

    def test_tablet_light_and_dark(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                context, page, errors = self.new_page(1024, 900, theme)
                self.assert_clean_render(page, errors)
                page.screenshot(path=str(ARTIFACTS / f"tablet-{theme}-1024x900.png"), full_page=True, timeout=90_000)
                context.close()

    def test_mobile_light_and_dark_navigation(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                context, page, errors = self.new_page(390, 844, theme)
                self.assert_clean_render(page, errors)
                page.get_by_role("button", name="Buka navigasi").click()
                self.assertTrue(page.locator(".sidebar").evaluate("node => node.classList.contains('is-open')"))
                navigation = page.get_by_role("navigation", name="Menu utama")
                self.assertEqual(navigation.get_by_role("button").count(), 7)
                expect(navigation.get_by_role("button", name=re.compile(r"^Transaksi"))).to_have_count(0)
                navigation.get_by_role("button", name=re.compile(r"^Proyek")).click()
                page.get_by_role("heading", name="Umur dan status proyek").wait_for()
                breadcrumb = page.locator(".breadcrumbs strong")
                expect(breadcrumb).to_have_text("Proyek")
                breadcrumb_metrics = breadcrumb.evaluate("node => ({ client: node.clientWidth, scroll: node.scrollWidth })")
                self.assertGreaterEqual(breadcrumb_metrics["client"], breadcrumb_metrics["scroll"], breadcrumb_metrics)
                overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                self.assertFalse(overflow)
                page.screenshot(path=str(ARTIFACTS / f"mobile-{theme}-390x844.png"), full_page=True, timeout=90_000)
                context.close()


    def test_owner_review_route_is_read_only_and_responsive(self):
        for width, height in ((390, 844), (1440, 1000)):
            with self.subTest(width=width):
                context, page, errors = self.new_page(width, height, "dark")
                page.goto(self.base_url, wait_until="domcontentloaded", timeout=90_000)
                page.goto(f"{self.base_url}#inbox-reviews", wait_until="domcontentloaded", timeout=90_000)
                page.get_by_role("heading", name="Perlu Ditinjau", exact=True).wait_for()
                expect(page.get_by_text("Tidak ada pesan yang menunggu keputusan.")).to_be_visible()
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"))
                self.assertEqual(errors, [])
                context.close()

    def test_projects_route_uses_lifecycle_market_and_project_registry(self):
        for width, height in ((390, 844), (1440, 1000)):
            with self.subTest(width=width):
                context, page, errors = self.new_page(width, height, "dark")
                page.goto(self.base_url, wait_until="domcontentloaded", timeout=90_000)
                page.get_by_role("heading", name="Pusat kendali keuangan Hollawall", exact=True).wait_for()
                if width <= 760:
                    page.get_by_role("button", name="Buka navigasi").click()
                page.locator(".sidebar nav button").filter(has_text="Proyek").click()
                page.get_by_role("heading", name="Umur dan status proyek", exact=True).wait_for()
                metrics = page.evaluate("""() => {
                  const visible = element => element.offsetParent !== null;
                  const report = document.querySelector('.project-market-report');
                  const controls = document.querySelector('.project-controls');
                  const register = document.querySelector('.project-register');
                  const targets = [...document.querySelectorAll('.project-market-toolbar button, .project-market-global-toolbar button, .project-register button, .project-ledger-pagination button')]
                    .filter(visible)
                    .map(element => element.getBoundingClientRect().height);
                  const viewports = [...document.querySelectorAll('.project-market-viewport')].filter(visible);
                  const completed = [...document.querySelectorAll('.project-market-candle.is-completed')].filter(visible);
                  return {
                    viewport: document.documentElement.clientWidth,
                    document: document.documentElement.scrollWidth,
                    canvases: document.querySelectorAll('.project-market-canvas').length,
                    candles: document.querySelectorAll('.project-market-candle').length,
                    months: document.querySelectorAll('.project-market-month').length,
                    completed: completed.length,
                    completedMarkers: document.querySelectorAll('.project-market-completed').length,
                    maskedAxes: [...document.querySelectorAll('.project-market-axis')].filter(axis => getComputedStyle(axis).backgroundImage !== 'none').length,
                    rows: document.querySelectorAll('.project-register > article').length,
                    quickComplete: document.querySelectorAll('button.complete-project-action[aria-label^="Selesaikan "]').length,
                    ordered: Boolean(report && controls && register && (report.compareDocumentPosition(controls) & Node.DOCUMENT_POSITION_FOLLOWING) && (controls.compareDocumentPosition(register) & Node.DOCUMENT_POSITION_FOLLOWING)),
                    internalHorizontalOverflow: viewports.every(element => element.scrollWidth > element.clientWidth),
                    minTarget: targets.length ? Math.min(...targets) : 0,
                  };
                }""")
                self.assertEqual(errors, [])
                self.assertLessEqual(metrics["document"], metrics["viewport"])
                self.assertEqual(metrics["canvases"], 4)
                self.assertGreater(metrics["candles"], 0)
                self.assertEqual(metrics["months"], 48)
                self.assertGreater(metrics["completed"], 0)
                self.assertEqual(metrics["completedMarkers"], metrics["completed"])
                self.assertEqual(metrics["maskedAxes"], 4)
                self.assertGreater(metrics["rows"], 0)
                self.assertEqual(metrics["quickComplete"], 0)
                self.assertTrue(metrics["ordered"])
                if width <= 760:
                    self.assertTrue(metrics["internalHorizontalOverflow"], metrics)
                    self.assertGreaterEqual(metrics["minTarget"], 44)
                context.close()

    def test_cashflow_and_wallet_routes_are_operational_and_paginated(self):
        context, page, errors = self.new_page(390, 844, "light")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=90_000)
        page.get_by_role("heading", name="Pusat kendali keuangan Hollawall", exact=True).wait_for()
        page.get_by_role("button", name="Buka navigasi").click()
        page.locator(".sidebar nav button").filter(has_text="Arus Kas").click()
        page.get_by_role("heading", name="Aliran kas, bukan sekadar saldo", exact=True).wait_for()
        expect(page.locator(".cashflow-workspace")).to_have_count(1)
        expect(page.get_by_text("Kas masuk eksternal")).to_be_visible()
        expect(page.locator(".ops-metric-strip article").filter(has_text="Transfer internal terbuka")).to_be_visible()
        expect(page.get_by_text(re.compile(r"Naufalspurnomo|Naufal Spurnomo", re.I))).to_have_count(0)

        page.get_by_role("button", name="Buka navigasi").click()
        page.locator(".sidebar nav button").filter(has_text="Dompet").click()
        page.get_by_role("heading", name="Posisi kas per sumber").wait_for()
        expect(page.locator(".wallet-workspace")).to_have_count(1)
        expect(page.get_by_text(re.compile(r"Dompet 1 dari 7", re.I))).to_be_visible()
        expect(page.get_by_role("navigation", name="Filter mutasi")).to_be_visible()

        ledger = page.locator(".ops-ledger article")
        self.assertEqual(ledger.count(), 8)
        expect(page.get_by_text(re.compile(r"Halaman 1 dari 2"))).to_be_visible()
        first_page = ledger.first.text_content()
        page.get_by_role("button", name="Berikutnya").click()
        expect(page.get_by_text(re.compile(r"Halaman 2 dari 2"))).to_be_visible()
        self.assertNotEqual(ledger.first.text_content(), first_page)
        self.assertEqual(ledger.count(), 3)

        page.get_by_role("button", name="Internal", exact=True).click()
        self.assertEqual(ledger.count(), 1)
        expect(page.get_by_text(re.compile(r"Naufalspurnomo|Naufal Spurnomo", re.I))).to_have_count(0)
        self.assertFalse(page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"))
        self.assertEqual(errors, [])
        context.close()

    def test_dark_routes_keep_readable_text_contrast(self):
        context, page, errors = self.new_page(1440, 1000, "dark")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=90_000)
        page.get_by_role("heading", name="Pusat kendali keuangan Hollawall", exact=True).wait_for()
        routes = (
            (None, ".executive-overview"),
            ("Arus Kas", ".cashflow-workspace"),
            ("Dompet", ".wallet-workspace"),
            ("Proyek", ".project-command-center"),
        )
        for route_name, selector in routes:
            if route_name:
                page.locator(".sidebar nav button").filter(has_text=route_name).click()
                page.locator(selector).wait_for()
            failures = page.evaluate("""() => {
              const parse = value => {
                const srgb = value.match(/color\\(srgb\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)(?:\\s*\\/\\s*([\\d.]+))?/);
                if (srgb) return [+srgb[1] * 255, +srgb[2] * 255, +srgb[3] * 255, srgb[4] ? +srgb[4] : 1];
                const rgb = value.match(/rgba?\\(([^)]+)\\)/);
                if (!rgb) return [0, 0, 0, 0];
                const channels = rgb[1].split(/[ ,/]+/).map(Number);
                return [channels[0], channels[1], channels[2], channels[3] ?? 1];
              };
              const blend = (foreground, background) => {
                const alpha = foreground[3] ?? 1;
                return [
                  foreground[0] * alpha + background[0] * (1 - alpha),
                  foreground[1] * alpha + background[1] * (1 - alpha),
                  foreground[2] * alpha + background[2] * (1 - alpha),
                  1,
                ];
              };
              const backgroundFor = element => {
                let result = [8, 10, 15, 1];
                const layers = [];
                for (let node = element; node; node = node.parentElement) layers.push(parse(getComputedStyle(node).backgroundColor));
                for (let index = layers.length - 1; index >= 0; index -= 1) result = blend(layers[index], result);
                return result;
              };
              const luminance = color => {
                const channels = color.slice(0, 3).map(value => {
                  const normalized = value / 255;
                  return normalized <= .03928 ? normalized / 12.92 : Math.pow((normalized + .055) / 1.055, 2.4);
                });
                return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
              };
              const ratio = (foreground, background) => {
                const a = luminance(foreground);
                const b = luminance(background);
                return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
              };
              return [...document.body.querySelectorAll('*')]
                .filter(element => {
                  const rect = element.getBoundingClientRect();
                  const style = getComputedStyle(element);
                  const ownsText = [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
                  return ownsText && rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                })
                .map(element => {
                  const style = getComputedStyle(element);
                  const background = backgroundFor(element);
                  const foreground = blend(parse(style.color), background);
                  const fontSize = parseFloat(style.fontSize);
                  const fontWeight = parseInt(style.fontWeight, 10) || 400;
                  const minimum = fontSize >= 24 || (fontSize >= 18 && fontWeight >= 700) ? 3 : 4.5;
                  return {
                    text: [...element.childNodes].filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent.trim()).join(' ').slice(0, 80),
                    contrast: ratio(foreground, background),
                    minimum,
                  };
                })
                .filter(item => item.contrast < item.minimum);
            }""")
            self.assertEqual(failures, [], {"route": route_name or "Ringkasan", "failures": failures})

        page.locator(".sidebar nav button").filter(has_text="Proyek").click()
        page.locator(".project-command-center").wait_for()
        titles = page.locator(".project-market-candle").evaluate_all("elements => elements.map(element => element.title)")
        self.assertTrue(titles)
        self.assertTrue(all(title and "mulai" in title and "umur" in title for title in titles))
        self.assertEqual(errors, [])
        context.close()

    def test_light_filled_color_surfaces_use_white_text(self):
        context, page, errors = self.new_page(1440, 1000, "light")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=90_000)
        page.get_by_role("heading", name="Pusat kendali keuangan Hollawall", exact=True).wait_for()
        routes = (
            (None, (
                ".workspace-switch", ".sidebar nav button.active", ".sidebar nav button b",
                ".business-mode-switch button.is-active", ".unit-option.is-active",
                ".new-project-button", ".vertical-project-bar",
            )),
            ("Proyek", (
                ".year-command nav button.active", ".project-market-candle:not(.is-planned) .project-market-body", ".project-market-completed",
            )),
            ("Arus Kas", (".ops-filter-block button.active",)),
            ("Dompet", (".wallet-rail button.active", ".movement-filters button.active")),
        )
        for route_name, selectors in routes:
            if route_name:
                page.locator(".sidebar nav button").filter(has_text=route_name).click()
                page.wait_for_timeout(50)
            failures = page.evaluate("""selectors => {
              const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
              };
              return selectors.flatMap(selector => [...document.querySelectorAll(selector)])
                .filter(visible)
                .flatMap(root => [root, ...root.querySelectorAll('*')])
                .filter(element => visible(element) && [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()))
                .map(element => ({
                  text: element.textContent.trim().replace(/\\s+/g, ' ').slice(0, 80),
                  selector: element.className || element.tagName,
                  color: getComputedStyle(element).color,
                }))
                .filter(item => item.color !== 'rgb(255, 255, 255)');
            }""", list(selectors))
            self.assertEqual(failures, [], {"route": route_name or "Ringkasan", "failures": failures})

        self.assertEqual(errors, [])
        context.close()

    def test_responsive_matrix_keeps_page_gutters_and_routes_inside_viewport(self):
        viewports = (
            (320, 720, "light"),
            (390, 844, "dark"),
            (844, 390, "light"),
            (768, 1024, "dark"),
            (1024, 768, "light"),
            (1280, 720, "dark"),
            (1440, 900, "light"),
            (1920, 1080, "dark"),
        )
        routes = ("Dashboard", "Arus Kas", "Dompet", "Proyek", "Operasional Kantor", "Hutang", "Laporan")
        for width, height, theme in viewports:
            with self.subTest(width=width, height=height, theme=theme):
                context, page, errors = self.new_page(width, height, theme)
                page.goto(self.base_url, wait_until="domcontentloaded", timeout=90_000)
                page.get_by_role("heading", name="Pusat kendali keuangan Hollawall", exact=True).wait_for()
                for route_name in routes:
                    page.locator(".sidebar nav button").filter(has_text=route_name).dispatch_event("click")
                    page.wait_for_timeout(25)
                    metrics = page.evaluate("""() => {
                      const content = document.querySelector('.content');
                      const rect = content.getBoundingClientRect();
                      const style = getComputedStyle(content);
                      const visible = element => element.offsetParent !== null;
                      const targets = [...document.querySelectorAll('.topbar button, .sidebar nav button, .unit-option')]
                        .filter(visible)
                        .map(element => ({ width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }));
                      return {
                        viewport: innerWidth,
                        document: document.documentElement.scrollWidth,
                        body: document.body.scrollWidth,
                        contentLeft: rect.left,
                        contentRight: rect.right,
                        paddingLeft: parseFloat(style.paddingLeft),
                        paddingRight: parseFloat(style.paddingRight),
                        mainMargin: parseFloat(getComputedStyle(document.querySelector('.main-canvas')).marginLeft),
                        mobileMenu: getComputedStyle(document.querySelector('.mobile-only')).display !== 'none',
                        targets,
                      };
                    }""")
                    self.assertLessEqual(metrics["document"], metrics["viewport"], {"route": route_name, **metrics})
                    self.assertLessEqual(metrics["body"], metrics["viewport"], {"route": route_name, **metrics})
                    self.assertGreaterEqual(metrics["paddingLeft"], 12)
                    self.assertGreaterEqual(metrics["paddingRight"], 12)
                    self.assertGreaterEqual(metrics["contentLeft"], 0)
                    self.assertLessEqual(metrics["contentRight"], width)
                    if width <= 900:
                        self.assertTrue(metrics["mobileMenu"])
                        self.assertEqual(metrics["mainMargin"], 0)
                        self.assertTrue(all(target["height"] >= 44 for target in metrics["targets"]), {"route": route_name, **metrics})
                if width <= 900:
                    page.get_by_role("button", name="Buka navigasi").click()
                    nav = page.locator(".sidebar nav")
                    scroll = nav.evaluate("element => ({client: element.clientHeight, scroll: element.scrollHeight})")
                    if scroll["scroll"] > scroll["client"]:
                        nav.evaluate("element => { element.scrollTop = element.scrollHeight }")
                        self.assertGreater(nav.evaluate("element => element.scrollTop"), 0)
                self.assertEqual(errors, [])
                context.close()

    def test_mobile_project_detail_keeps_title_actions_and_ledger_fully_usable(self):
        context, page, errors = self.new_page(390, 844)
        page.goto(f"{self.base_url}/#projects?project=00000000-0000-4000-8000-000000000001", wait_until="domcontentloaded", timeout=90_000)
        page.get_by_role("heading", name="Surabaya Office", exact=True).wait_for()
        metrics = page.evaluate("""() => {
          const size = selector => {
            const element = document.querySelector(selector);
            const rect = element?.getBoundingClientRect();
            return rect ? { width: rect.width, height: rect.height } : null;
          };
          const wrap = document.querySelector('.project-transaction-detail .workspace-table-wrap');
          const actions = [...document.querySelectorAll('.project-transaction-detail .row-actions button')].map(element => element.getBoundingClientRect().height);
          return {
            breadcrumb: document.querySelector('.breadcrumbs strong')?.textContent?.trim(),
            back: size('.project-detail-back'),
            addCount: document.querySelectorAll('.project-detail-head .primary-button').length,
            tableClient: wrap?.clientWidth ?? 0,
            tableScroll: wrap?.scrollWidth ?? 0,
            actionHeights: actions,
            document: document.documentElement.scrollWidth,
            viewport: document.documentElement.clientWidth,
          };
        }""")
        self.assertEqual(metrics["breadcrumb"], "Surabaya Office")
        self.assertGreaterEqual(metrics["back"]["height"], 44)
        self.assertEqual(metrics["addCount"], 0)
        self.assertLessEqual(metrics["tableScroll"], metrics["tableClient"])
        self.assertEqual(metrics["actionHeights"], [])
        self.assertLessEqual(metrics["document"], metrics["viewport"])
        self.assertEqual(errors, [])
        context.close()

    def test_legacy_transaction_route_canonicalizes_to_live_read_only_project(self):
        context, page, errors = self.new_page(1440, 1000)
        page.goto(f"{self.base_url}/#transactions?project=00000000-0000-4000-8000-000000000001", wait_until="domcontentloaded", timeout=90_000)
        page.get_by_role("heading", name="Surabaya Office", exact=True).wait_for()
        self.assertEqual(page.evaluate("window.location.hash"), "#projects?project=00000000-0000-4000-8000-000000000001")
        expect(page.locator(".project-detail-head").get_by_role("button", name="Tambah transaksi", exact=True)).to_have_count(0)
        self.assertIsNone(page.evaluate("localStorage.getItem('hollawall-finance-demo-v3')"))

        page.get_by_role("button", name="Kembali ke Proyek").click()
        page.get_by_role("heading", name="Umur dan status proyek", exact=True).wait_for()
        self.assertEqual(page.evaluate("window.location.hash"), "#projects")
        self.assertEqual(errors, [])
        context.close()


if __name__ == "__main__":
    unittest.main()
