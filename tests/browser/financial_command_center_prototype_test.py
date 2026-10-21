import contextlib
import functools
import http.server
import os
from pathlib import Path
import socketserver
import threading
import unittest

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = ROOT / "prototypes" / "financial-command-center"
ARTIFACTS = ROOT / "artifacts" / "dashboard-prototype"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        del format, args
        return


@contextlib.contextmanager
def serve(directory: Path):
    handler = functools.partial(_QuietHandler, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        port = server.server_address[1]
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.shutdown()
            worker.join(timeout=5)


class FinancialCommandCenterPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        cls._server_context = serve(PROTOTYPE)
        cls.base_url = cls._server_context.__enter__()
        cls._playwright = sync_playwright().start()
        executable = os.environ.get("CHROMIUM_PATH", "/snap/bin/chromium")
        cls.browser = cls._playwright.chromium.launch(
            headless=True,
            executable_path=executable if Path(executable).exists() else None,
            args=["--no-sandbox"],
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._playwright.stop()
        cls._server_context.__exit__(None, None, None)

    def new_page(self, width=1440, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        console_errors = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        return page, console_errors

    def test_overview_renders_required_owner_information(self):
        page, errors = self.new_page()
        page.goto(self.base_url, wait_until="networkidle")

        self.assertEqual(page.title(), "Ringkasan Perusahaan — Hollawall")
        self.assertTrue(page.get_by_text("DATA DEMO", exact=False).is_visible())
        self.assertEqual(page.locator(".kpi").count(), 6)
        self.assertEqual(page.locator(".wallet-row").count(), 3)
        self.assertTrue(page.get_by_text("Saldo kas", exact=True).is_visible())
        self.assertTrue(page.get_by_text("Arus kas proyek bersih", exact=True).is_visible())
        self.assertEqual(errors, [])

        page.screenshot(path=str(ARTIFACTS / "overview-1440x900.png"), full_page=True)
        page.close()

    def test_filter_and_kpi_drilldown_update_view_and_url(self):
        page, errors = self.new_page(1280, 720)
        page.goto(self.base_url, wait_until="networkidle")

        page.locator("[data-testid=wallet-filter]").select_option("TX SBY(216)")
        self.assertIn("wallet=TX+SBY%28216%29", page.url)
        page.locator("[data-testid=kpi-outflow]").click()

        self.assertTrue(page.locator("[data-testid=transaction-table]").is_visible())
        self.assertIn("view=transactions", page.url)
        self.assertTrue(page.get_by_text("Semua Transaksi", exact=True).is_visible())
        self.assertGreater(page.locator("[data-testid=transaction-table] tbody tr").count(), 0)
        self.assertEqual(errors, [])

        page.screenshot(path=str(ARTIFACTS / "transactions-1280x720.png"), full_page=True)
        page.close()

    def test_mobile_navigation_has_no_horizontal_overflow(self):
        page, errors = self.new_page(390, 844)
        page.goto(self.base_url, wait_until="networkidle")

        overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        self.assertFalse(overflow)
        page.get_by_role("button", name="Buka navigasi").click()
        self.assertTrue(page.locator("#sidebar").evaluate("node => node.classList.contains('is-open')"))
        page.locator("[data-testid=nav-transactions]").click()
        self.assertTrue(page.get_by_text("Semua Transaksi", exact=True).is_visible())
        self.assertEqual(errors, [])

        page.screenshot(path=str(ARTIFACTS / "mobile-390x844.png"), full_page=True)
        page.close()

    def test_stale_state_is_explicit(self):
        page, errors = self.new_page()
        page.goto(f"{self.base_url}/?stale=1", wait_until="networkidle")

        self.assertTrue(page.get_by_text("Data terlambat diperbarui.", exact=True).is_visible())
        self.assertEqual(errors, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
