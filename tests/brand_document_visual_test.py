from contextlib import contextmanager
from pathlib import Path
import os
import signal
import shutil
import socket
import subprocess
import sys
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
    npm = shutil.which("npm") or "npm"
    command = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)]
    if os.name == "nt" and npm.lower().endswith((".cmd", ".bat")):
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *command]
    process = subprocess.Popen(
        command,
        cwd=DASHBOARD,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
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
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def test_brand_document_pages_have_distinct_geometry_and_no_overflow():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with visual_server() as url, sync_playwright() as playwright:
        executable = os.environ.get("CHROMIUM_PATH") or shutil.which("google-chrome") or shutil.which("chromium")
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
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
          master: node.querySelector('.commercial-template-master')?.currentSrc,
          masterWidth: node.querySelector('.commercial-template-master')?.naturalWidth,
          masterHeight: node.querySelector('.commercial-template-master')?.naturalHeight,
          }))""")
        assert [(item["template"], item["pageSize"]) for item in metrics] == [
            ("hollawall", "A5"), ("hojja", "A4"),
            ("texturin-surabaya", "A4"), ("texturin-bali", "A4")
        ]
        assert all(item["overflowStyle"] == "hidden" and item["overflowY"] <= 1 for item in metrics)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        assert metrics[0]["height"] / metrics[0]["width"] > metrics[1]["height"] / metrics[1]["width"]
        assert len({item["master"] for item in metrics}) == 4
        assert all(item["masterWidth"] > 0 and item["masterHeight"] > 0 for item in metrics)
        assert console_errors == []
        page.screenshot(path=str(ARTIFACTS / "desktop-1440x1100.png"), full_page=False)
        page.set_viewport_size({"width": 2800, "height": 1200})
        for index, template in enumerate(("hollawall", "hojja", "texturin-surabaya", "texturin-bali")):
            pages.nth(index).screenshot(path=str(ARTIFACTS / f"{template}-native.png"))

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
