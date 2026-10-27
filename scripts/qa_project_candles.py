#!/usr/bin/env python3
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:4173/"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "project-candle-qa"
FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "project-candle-snapshot.json"
OUT.mkdir(parents=True, exist_ok=True)
snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path="/snap/bin/chromium", args=["--no-sandbox"])
    for name, width, height in (("macbook", 1440, 900), ("mobile", 390, 844)):
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.route("**/data/dashboard-snapshot.json", lambda route: route.fulfill(json=snapshot))
        page.goto(URL, wait_until="networkidle")
        if width <= 900:
            page.get_by_role("button", name="Buka navigasi").click()
        page.get_by_role("button", name="Proyek", exact=True).click()
        page.get_by_role("heading", name="Timeline kalender proyek aktif").wait_for()

        candles = page.locator("[data-project-candle]")
        count = candles.count()
        assert count == 5, (name, count)
        styles = [candles.nth(index).get_attribute("style") for index in range(count)]
        assert len(set(styles)) == count, styles
        assert page.get_by_text("Garis putih = rentang transaksi", exact=True).count() == 2
        assert page.get_by_text("Titik bawah: transaksi pertama · titik atas: transaksi terakhir", exact=True).count() == 2

        first_name = candles.first.get_attribute("data-project-candle")
        candles.first.click()
        page.get_by_role("heading", name="Semua Transaksi").wait_for()
        assert page.locator('input[placeholder="Cari transaksi…"]').input_value() == first_name
        assert not errors, errors

        if width <= 900:
            page.get_by_role("button", name="Buka navigasi").click()
        page.get_by_role("button", name="Proyek", exact=True).click()
        page.get_by_role("heading", name="Timeline kalender proyek aktif").wait_for()
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        page.close()

    browser.close()

print("project-candle browser QA: macbook+mobile PASS")
