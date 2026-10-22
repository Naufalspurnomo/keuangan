import contextlib
import functools
import http.server
import json
from pathlib import Path
import re
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
TRANSACTIONS = [
    {"id": 1, "transaction_date": "2026-10-21", "transaction_type": "Pemasukan", "amount": 125_000_000, "wallet": "TX SBY(216)", "company": "Hollawall", "project": "Surabaya Office", "notes": "Termin pekerjaan utama"},
    {"id": 2, "transaction_date": "2026-10-20", "transaction_type": "Pengeluaran", "amount": 18_400_000, "wallet": "BCA(056)", "company": "Hollawall", "project": "Grand Galaxy", "notes": "Material dan vendor"},
    {"id": 3, "transaction_date": "2026-10-19", "transaction_type": "Pemasukan", "amount": 87_500_000, "wallet": "KPR BRI(031)", "company": "Hollawall", "project": "Mawar Residence", "notes": "Pembayaran progres"},
    {"id": 4, "transaction_date": "2026-10-18", "transaction_type": "Pengeluaran", "amount": 26_750_000, "wallet": "TX SBY(216)", "company": "Hollawall", "project": "Surabaya Office", "notes": "Operasional lapangan"},
    {"id": 5, "transaction_date": "2026-10-17", "transaction_type": "Pemasukan", "amount": 70_000_000, "wallet": "BCA(056)", "company": "Hollawall", "project": "Grand Galaxy", "notes": "Termin kedua"},
    {"id": 6, "transaction_date": "2026-10-16", "transaction_type": "Pengeluaran", "amount": 35_400_000, "wallet": "KPR BRI(031)", "company": "Hollawall", "project": "Mawar Residence", "notes": "Pembelian material"},
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
        {"name": "Surabaya Office", "net_cashflow": 98_250_000},
        {"name": "Grand Galaxy", "net_cashflow": 51_600_000},
        {"name": "Mawar Residence", "net_cashflow": 52_100_000},
    ],
}


UPDATED_SNAPSHOT = json.loads(json.dumps(SNAPSHOT))
UPDATED_SNAPSHOT["overview"]["metrics"]["operating_inflow"] += 40_000_000
UPDATED_SNAPSHOT["overview"]["metrics"]["operating_outflow"] += 5_000_000
UPDATED_SNAPSHOT["overview"]["metrics"]["net_operating_cashflow"] += 35_000_000
UPDATED_SNAPSHOT["overview"]["counts"]["valid_rows"] += 2
UPDATED_SNAPSHOT["meta"]["as_of"] = "2026-10-22T08:10:00Z"
UPDATED_SNAPSHOT["meta"]["data_through"] = "2026-10-22"
UPDATED_SNAPSHOT["transactions"] = [
    {"id": 7, "transaction_date": "2026-10-22", "transaction_type": "Pemasukan", "amount": 40_000_000, "wallet": "TX SBY(216)", "company": "Hollawall", "project": "Surabaya Office", "notes": "Termin baru proyek", "internal_movement": False, "transfer_scope": "external", "source_key": "TX SBY(216):pemasukan:217"},
    {"id": 8, "transaction_date": "2026-10-22", "transaction_type": "Pengeluaran", "amount": 5_000_000, "wallet": "TX SBY(216)", "company": "Hollawall", "project": "Surabaya Office", "notes": "Reversal termin salah", "internal_movement": False, "transfer_scope": "external", "source_key": "TX SBY(216):pengeluaran:218"},
    *UPDATED_SNAPSHOT["transactions"],
]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
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
        cls.browser = cls.playwright.chromium.launch(
            headless=True,
            executable_path="/snap/bin/chromium",
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

        context.route("**/live-api/snapshot", route_api)
        page = context.new_page()
        console_errors = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        return context, page, console_errors

    def new_dynamic_page(self, width, height, theme="light"):
        context = self.browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme)
        context.add_init_script(f"localStorage.setItem('hollawall-theme', '{theme}')")
        page = context.new_page()
        page.clock.install()
        console_errors = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        state = {"calls": 0}

        def route_api(route):
            state["calls"] += 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps(SNAPSHOT if state["calls"] == 1 else UPDATED_SNAPSHOT))

        context.route("**/live-api/snapshot", route_api)
        return context, page, console_errors, state

    def assert_clean_render(self, page, errors):
        page.goto(self.base_url, wait_until="networkidle")
        page.get_by_role("heading", name="Ringkasan Perusahaan").wait_for()
        page.locator(".recharts-responsive-container").first.wait_for()
        self.assertEqual(errors, [])
        metrics = page.evaluate("""() => ({
          viewport: document.documentElement.clientWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          theme: document.documentElement.dataset.theme,
          chartCount: document.querySelectorAll('.recharts-responsive-container').length,
          visibleButtons: [...document.querySelectorAll('button')].filter(el => el.offsetParent !== null).length,
          metricColors: [...document.querySelectorAll('.metric-card strong')].map(el => getComputedStyle(el).color),
          walletLegend: [...document.querySelectorAll('.donut-legend li')].map(el => el.textContent),
          walletTotal: document.querySelector('.donut-center strong')?.textContent
        })""")
        self.assertIn("Lainnya", " ".join(metrics["walletLegend"]))
        self.assertEqual(metrics["walletTotal"], "968,9 jt")
        self.assertLessEqual(metrics["document"], metrics["viewport"])
        self.assertLessEqual(metrics["body"], metrics["viewport"])
        # Overview renders multiple independent charts: cash area, project bars,
        # monthly flow, wallet composition. Lock the contract, not an exact count,
        # so adding a panel does not silently drop an existing one.
        self.assertGreaterEqual(metrics["chartCount"], 4)
        self.assertEqual(len(set(metrics["metricColors"])), 4)
        self.assertGreater(metrics["visibleButtons"], 8)
        return metrics

    def test_desktop_light_and_dark(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                context, page, errors = self.new_page(1440, 1000, theme)
                metrics = self.assert_clean_render(page, errors)
                self.assertEqual(metrics["theme"], theme)
                page.screenshot(path=str(ARTIFACTS / f"desktop-{theme}-1440x1000.png"), full_page=True)
                context.close()

    def test_tablet_light_and_dark(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                context, page, errors = self.new_page(1024, 900, theme)
                self.assert_clean_render(page, errors)
                page.screenshot(path=str(ARTIFACTS / f"tablet-{theme}-1024x900.png"), full_page=True)
                context.close()

    def test_mobile_light_and_dark_navigation(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                context, page, errors = self.new_page(390, 844, theme)
                self.assert_clean_render(page, errors)
                page.get_by_role("button", name="Buka navigasi").click()
                self.assertTrue(page.locator(".sidebar").evaluate("node => node.classList.contains('is-open')"))
                page.locator(".sidebar nav button").filter(has_text="Transaksi").click()
                page.get_by_role("heading", name="Semua Transaksi").wait_for()
                overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                self.assertFalse(overflow)
                page.screenshot(path=str(ARTIFACTS / f"mobile-{theme}-390x844.png"), full_page=True)
                context.close()


    def test_live_refresh_shows_new_transaction_and_reversal_within_target(self):
        context, page, errors, state = self.new_dynamic_page(1440, 1000)
        page.goto(self.base_url, wait_until="networkidle")
        page.get_by_role("heading", name="Ringkasan Perusahaan").wait_for()
        page.get_by_role("button", name="Arus kas operasional bersih").click()
        expect(page.get_by_text("Termin baru proyek")).to_be_hidden()
        expect(page.get_by_text("Reversal termin salah")).to_be_hidden()

        page.clock.run_for(10_000)

        expect(page.get_by_text("Termin baru proyek")).to_be_visible()
        expect(page.get_by_text("Reversal termin salah")).to_be_visible()
        page.get_by_role("button", name="Ringkasan").click()
        expect(page.get_by_role("button", name="Arus kas operasional bersih").locator("strong")).to_have_text(re.compile(r"340\.350\.000"))
        self.assertGreaterEqual(state["calls"], 2)
        self.assertEqual(errors, [])
        context.close()


if __name__ == "__main__":
    unittest.main()
