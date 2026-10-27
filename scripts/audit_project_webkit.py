#!/usr/bin/env python3
"""Safari-equivalent WebKit regression checks for the Project workspace."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "scripts" / "audit_project_matrix.py"
spec = importlib.util.spec_from_file_location("project_matrix", MATRIX_PATH)
assert spec and spec.loader
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)
SNAPSHOT = matrix.dense_snapshot()
OUT = ROOT / "artifacts" / "project-matrix-qa"

with sync_playwright() as p:
    browser = p.webkit.launch(headless=True)
    for label, width, height in (("webkit-1024", 1024, 768), ("webkit-macbook", 1440, 900), ("webkit-macbook-pro", 1512, 982)):
        page = browser.new_page(viewport={"width": width, "height": height}, timezone_id="Asia/Jakarta")
        console_errors: list[str] = []
        page_errors: list[str] = []
        request_failures: list[str] = []
        page.on("console", lambda message, errors=console_errors: errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error, errors=page_errors: errors.append(str(error)))
        page.on("requestfailed", lambda request, failures=request_failures: failures.append(f"{request.method} {request.url}: {request.failure}"))
        page.route("**/data/dashboard-snapshot.json", lambda route, _request=None: route.fulfill(json=SNAPSHOT))
        page.goto(matrix.URL, wait_until="networkidle")
        matrix.open_projects(page)
        matrix.assert_no_document_overflow(page, label)
        matrix.assert_key_blocks_inside_viewport(page, label)
        matrix.assert_no_cue_overlap(page, label)

        candles = page.locator("[data-project-candle]")
        assert candles.count() == 20, (label, candles.count())
        first_name = candles.first.get_attribute("data-project-candle")
        candles.first.click()
        page.get_by_role("heading", name="Semua Transaksi").wait_for()
        assert page.locator('input[placeholder="Cari transaksi…"]').input_value() == first_name
        matrix.open_projects(page)

        second_name = page.locator("[data-project-candle]").nth(1).get_attribute("data-project-candle")
        page.locator("[data-project-candle]").nth(1).focus()
        page.keyboard.press("Enter")
        page.get_by_role("heading", name="Semua Transaksi").wait_for()
        assert page.locator('input[placeholder="Cari transaksi…"]').input_value() == second_name
        matrix.open_projects(page)

        page.locator('input[placeholder="Cari nama proyek…"]').fill("Project 01")
        assert page.locator("[data-project-candle]").count() == 1
        assert page.locator(".project-ledger-row").count() == 1
        page.locator('input[placeholder="Cari nama proyek…"]').fill("")
        page.get_by_role("button", name="Data aktual", exact=True).click()
        page.get_by_text("Umur proyek dari snapshot", exact=True).wait_for()
        page.get_by_role("button", name="Demo variasi", exact=True).click()
        page.get_by_text("Variasi warna untuk uji visual", exact=True).wait_for()

        assert not console_errors, (label, console_errors)
        assert not page_errors, (label, page_errors)
        assert not request_failures, (label, request_failures)
        page.screenshot(path=str(OUT / f"{label}.png"), full_page=True)
        page.close()
    browser.close()

print("project WebKit QA: 3 laptop/MacBook viewports PASS")
