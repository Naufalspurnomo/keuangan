from contextlib import contextmanager
from pathlib import Path
import os
import signal
import socket
import subprocess
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
ARTIFACTS = ROOT / "artifacts" / "brand-commercial-documents"


@contextmanager
def visual_server():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=DASHBOARD,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    url = f"http://127.0.0.1:{port}/tests/visual/brand-documents.html"
    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None:
                raise RuntimeError("visual Vite server exited before readiness")
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("visual Vite server did not become ready")
                time.sleep(0.1)
        yield url
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def test_brand_document_pages_have_distinct_geometry_and_no_overflow():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with visual_server() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path="/usr/bin/google-chrome")
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        console_errors: list[str] = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(url, wait_until="networkidle")
        pages = page.locator(".brand-document")
        assert pages.count() == 4
        metrics = pages.evaluate_all("""nodes => nodes.map(node => ({
          template: node.dataset.template,
          pageSize: node.dataset.pageSize,
          width: node.getBoundingClientRect().width,
          height: node.getBoundingClientRect().height,
          overflowY: node.scrollHeight - node.clientHeight,
          overflowStyle: getComputedStyle(node).overflow,
          background: getComputedStyle(node).backgroundColor,
        }))""")
        assert [(item["template"], item["pageSize"]) for item in metrics] == [
            ("hollawall", "A5"), ("hojja", "A4"),
            ("texturin-surabaya", "A4"), ("texturin-bali", "A4")
        ]
        assert all(item["overflowStyle"] == "hidden" and item["overflowY"] <= 1 for item in metrics)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        assert metrics[0]["height"] / metrics[0]["width"] > metrics[1]["height"] / metrics[1]["width"]
        assert len({item["background"] for item in metrics}) >= 2
        assert console_errors == []
        page.screenshot(path=str(ARTIFACTS / "desktop-1440x1100.png"), full_page=False)

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        mobile.goto(url, wait_until="networkidle")
        mobile_pages = mobile.locator(".brand-document")
        assert mobile_pages.count() == 4
        assert all(value == "hidden" for value in mobile_pages.evaluate_all(
            "nodes => nodes.map(node => getComputedStyle(node).overflow)"
        ))
        assert mobile.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        mobile.screenshot(path=str(ARTIFACTS / "mobile-390x844.png"), full_page=True)
        browser.close()
