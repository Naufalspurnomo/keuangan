#!/usr/bin/env python3
"""Dense desktop/laptop regression audit for the Hollawall Project workspace."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE_FIXTURE = ROOT / "tests" / "fixtures" / "project-candle-snapshot.json"
OUT = ROOT / "artifacts" / "project-matrix-qa"
URL = "http://127.0.0.1:4173/"
VIEWPORTS = (
    ("laptop-1024", 1024, 768),
    ("laptop-1280", 1280, 800),
    ("laptop-1366", 1366, 768),
    ("macbook-air", 1440, 900),
    ("macbook-pro", 1512, 982),
    ("desktop-fhd", 1920, 1080),
)


def dense_snapshot() -> dict[str, Any]:
    data = json.loads(BASE_FIXTURE.read_text(encoding="utf-8"))
    projects: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    portfolios = ("Hollawall", "Texturin")
    for portfolio_index, portfolio in enumerate(portfolios):
        for index in range(14):
            project_number = portfolio_index * 14 + index + 1
            name = (
                f"{portfolio} Project {project_number:02d}"
                if index != 4
                else f"{portfolio} Renovasi Interior Hunian dengan Nama Sangat Panjang {project_number:02d}"
            )
            age = 3 + index * 7
            completed = index == 13
            health = "completed" if completed else "healthy" if age <= 14 else "watch" if age <= 30 else "overdue"
            started_day = max(1, 21 - min(age, 20))
            project = {
                "name": name,
                "portfolio": portfolio,
                "net_cashflow": (-1 if index % 4 == 0 else 1) * (project_number * 1_250_000),
                "transaction_count": 1,
                "first_activity_on": f"2026-07-{(index % 27) + 1:02d}",
                "last_activity_on": f"2026-10-{max(1, 20 - index):02d}",
                "started_on": f"2026-07-{started_day:02d}",
                "completed_on": "2026-10-20" if completed else None,
                "age_days": age,
                "lifecycle_status": "completed" if completed else "active",
                "health": health,
            }
            projects.append(project)
            transactions.append({
                "id": project_number,
                "source_key": f"QA:{project_number}",
                "transaction_date": f"2026-10-{max(1, 21 - (index % 20)):02d}",
                "transaction_type": "Pengeluaran" if index % 4 == 0 else "Pemasukan",
                "amount": abs(project["net_cashflow"]),
                "wallet": "CV HB(101)",
                "company": "HOLLA" if portfolio == "Hollawall" else "TEXTURIN",
                "project": name,
                "notes": "Transaksi audit matriks",
                "internal_movement": False,
            })
    data["project_summaries"] = projects
    data["transactions"] = transactions
    data["meta"]["data_completeness"] = {"valid_rows": len(transactions), "invalid_rows": 0, "completeness_pct": 100}
    data["overview"]["counts"] = {"valid_rows": len(transactions), "invalid_rows": 0}
    return data


def open_projects(page: Page) -> None:
    if page.get_by_role("button", name="Buka navigasi").is_visible():
        page.get_by_role("button", name="Buka navigasi").click()
    page.get_by_role("button", name="Proyek", exact=True).click()
    page.get_by_role("heading", name="Timeline kalender proyek aktif").wait_for()


def assert_no_document_overflow(page: Page, label: str) -> None:
    metrics = page.evaluate("""() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      bodyWidth: document.body.scrollWidth
    })""")
    assert metrics["documentWidth"] <= metrics["viewportWidth"] + 1, (label, metrics)
    assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1, (label, metrics)


def assert_key_blocks_inside_viewport(page: Page, label: str) -> None:
    selectors = [
        ".topbar", ".page-heading", ".snapshot-context", ".project-register-head",
        ".project-explorer", ".candle-demo-control", ".active-project-age-report",
        ".project-ledger-results",
    ]
    failures = page.evaluate("""(selectors) => {
      const width = document.documentElement.clientWidth;
      return selectors.flatMap(selector => [...document.querySelectorAll(selector)].filter(el => {
        const s = getComputedStyle(el); const r = el.getBoundingClientRect();
        return s.display !== 'none' && (r.left < -1 || r.right > width + 1 || r.width > width + 1);
      }).map(el => ({selector, left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right, width: el.getBoundingClientRect().width})));
    }""", selectors)
    assert not failures, (label, failures)


def assert_no_cue_overlap(page: Page, label: str) -> None:
    overlaps = page.evaluate("""() => [...document.querySelectorAll('.active-calendar-frame')].flatMap(frame => {
      const cue = frame.querySelector('.active-calendar-pan-cue');
      const viewport = frame.querySelector('.active-calendar-viewport');
      if (!cue || !viewport) return [];
      const c = cue.getBoundingClientRect();
      const v = viewport.getBoundingClientRect();
      return [...frame.querySelectorAll('[data-project-candle]')].filter(el => {
        const r = el.getBoundingClientRect();
        const visibleLeft = Math.max(r.left, v.left);
        const visibleRight = Math.min(r.right, v.right);
        const visibleTop = Math.max(r.top, v.top);
        const visibleBottom = Math.min(r.bottom, v.bottom);
        if (visibleRight <= visibleLeft || visibleBottom <= visibleTop) return false;
        return Math.max(0, Math.min(c.right, visibleRight) - Math.max(c.left, visibleLeft)) > 2 &&
               Math.max(0, Math.min(c.bottom, visibleBottom) - Math.max(c.top, visibleTop)) > 2;
      }).map(el => el.getAttribute('data-project-candle'));
    })""")
    assert not overlaps, (label, "pan cue overlaps project candles", overlaps)


def run_interactions(page: Page, label: str) -> None:
    candles = page.locator("[data-project-candle]")
    assert candles.count() == 20, (label, "expected first page of 10 candles for each active portfolio", candles.count())
    overflow_count = page.locator(".active-calendar-viewport").evaluate_all("els => els.filter(el => el.scrollWidth > el.clientWidth + 1).length")
    cue_count = page.locator(".active-calendar-pan-cue").count()
    assert cue_count == overflow_count, (label, "scroll cue does not match overflow state", cue_count, overflow_count)
    assert page.get_by_text("Garis putih = rentang transaksi", exact=True).count() == 2
    assert page.get_by_text("Titik bawah: transaksi pertama · titik atas: transaksi terakhir", exact=True).count() == 2
    styles = [candles.nth(i).get_attribute("style") for i in range(candles.count())]
    assert len(set(styles)) >= 10, (label, "insufficient age-color variation", len(set(styles)))

    # Mouse activation must open the matching transaction query.
    first_name = candles.first.get_attribute("data-project-candle")
    candles.first.click()
    page.get_by_role("heading", name="Semua Transaksi").wait_for()
    assert page.locator('input[placeholder="Cari transaksi…"]').input_value() == first_name
    open_projects(page)

    # Keyboard activation must behave like a native button.
    keyboard_candle = page.locator("[data-project-candle]").nth(1)
    keyboard_name = keyboard_candle.get_attribute("data-project-candle")
    keyboard_candle.focus()
    page.keyboard.press("Enter")
    page.get_by_role("heading", name="Semua Transaksi").wait_for()
    assert page.locator('input[placeholder="Cari transaksi…"]').input_value() == keyboard_name
    open_projects(page)

    # Desktop pointer drag must scroll the empty chart area without activating a project.
    viewport = page.locator(".active-calendar-viewport").first
    viewport.scroll_into_view_if_needed()
    is_overflowing = viewport.evaluate("el => el.scrollWidth > el.clientWidth + 1")
    before = viewport.evaluate("el => el.scrollLeft")
    box = viewport.bounding_box()
    assert box
    if is_overflowing:
        # Start on the month-axis gutter, which is deliberately outside all candle buttons.
        page.mouse.move(box["x"] + 55, box["y"] + box["height"] * .55)
        page.mouse.down()
        page.mouse.move(box["x"] - 220, box["y"] + box["height"] * .55, steps=8)
        page.mouse.up()
        after = viewport.evaluate("el => el.scrollLeft")
        assert after > before, (label, "mouse drag did not pan", before, after)
    assert page.get_by_role("heading", name="Timeline kalender proyek aktif").is_visible()

    # Pan cue must advance the viewport and remain outside candle hit boxes.
    if is_overflowing:
        viewport.evaluate("el => el.scrollLeft = 0")
        page.wait_for_timeout(100)
        cue = page.locator(".active-calendar-pan-cue").first
        cue.click()
        page.wait_for_timeout(100)
        assert viewport.evaluate("el => el.scrollLeft") > 0, (label, "pan cue did not move chart")

    # Source mode toggles must change copy and preserve real project targets.
    page.get_by_role("button", name="Data aktual", exact=True).click()
    page.get_by_text("Umur proyek dari snapshot", exact=True).wait_for()
    actual_style = page.locator("[data-project-candle]").nth(9).get_attribute("style")
    page.get_by_role("button", name="Demo variasi", exact=True).click()
    page.get_by_text("Variasi warna untuk uji visual", exact=True).wait_for()
    demo_style = page.locator("[data-project-candle]").nth(9).get_attribute("style")
    assert actual_style != demo_style, (label, "demo/actual mode produced same candle style")

    # Query filters both candles and actual ledger rows.
    search = page.locator('input[placeholder="Cari nama proyek…"]')
    search.fill("Project 01")
    assert page.locator("[data-project-candle]").count() == 1, (label, "chart search mismatch")
    assert page.locator(".project-ledger-row").count() == 1, (label, "ledger search mismatch")
    search.fill("")

    # Portfolio filter must reduce both chart sections and ledger grouping.
    page.get_by_role("button", name="Filter portfolio Texturin", exact=True).click()
    assert page.locator(".active-age-section").count() == 1
    assert page.locator(".portfolio-project-group").count() == 1
    page.get_by_role("button", name="Filter portfolio Semua portfolio", exact=True).click()

    # Ledger pagination and row click.
    next_button = page.get_by_role("button", name="Berikutnya", exact=True)
    assert next_button.is_visible() and next_button.is_enabled(), (label, "ledger pagination missing")
    next_button.click()
    page.get_by_text("Halaman 2 / 3", exact=True).wait_for()
    previous_button = page.get_by_role("button", name="Sebelumnya", exact=True)
    previous_button.click()
    page.get_by_text("Halaman 1 / 3", exact=True).wait_for()
    row = page.locator(".project-ledger-row").first
    row_name = row.locator(".project-ledger-main strong").inner_text()
    row.click()
    page.get_by_role("heading", name="Semua Transaksi").wait_for()
    assert page.locator('input[placeholder="Cari transaksi…"]').input_value() == row_name
    open_projects(page)

    # Completed list removes candle section and shows only completed actual rows.
    page.get_by_role("button", name="Selesai", exact=True).click()
    assert page.locator(".active-project-age-report").count() == 0
    assert page.locator(".project-ledger-row").count() == 2
    page.get_by_role("button", name="Semua", exact=True).click()

    # Theme toggle must not destroy state/layout.
    page.get_by_role("button", name="Ubah tema").click()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.get_by_role("heading", name="Timeline kalender proyek aktif").is_visible()
    page.get_by_role("button", name="Ubah tema").click()
    assert page.locator("html").get_attribute("data-theme") == "light"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot = dense_snapshot()
    results: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path="/snap/bin/chromium", args=["--no-sandbox"])
        for label, width, height in VIEWPORTS:
            page = browser.new_page(viewport={"width": width, "height": height}, timezone_id="Asia/Jakarta")
            console_errors: list[str] = []
            page_errors: list[str] = []
            failed_requests: list[str] = []
            page.on("console", lambda message, errors=console_errors: errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error, errors=page_errors: errors.append(str(error)))
            page.on("requestfailed", lambda request, failures=failed_requests: failures.append(f"{request.method} {request.url}: {request.failure}"))
            page.route("**/data/dashboard-snapshot.json", lambda route, _request=None, payload=snapshot: route.fulfill(json=payload))
            page.goto(URL, wait_until="networkidle")
            open_projects(page)
            assert_no_document_overflow(page, label)
            assert_key_blocks_inside_viewport(page, label)
            assert_no_cue_overlap(page, label)
            run_interactions(page, label)
            assert_no_document_overflow(page, f"{label}-after-interactions")
            assert_key_blocks_inside_viewport(page, f"{label}-after-interactions")
            assert_no_cue_overlap(page, f"{label}-after-interactions")
            assert not console_errors, (label, "console errors", console_errors)
            assert not page_errors, (label, "page errors", page_errors)
            assert not failed_requests, (label, "request failures", failed_requests)
            page.screenshot(path=str(OUT / f"{label}.png"), full_page=True)
            results.append({"viewport": label, "width": width, "height": height, "status": "PASS"})
            page.close()

        # Responsive state change: cue must appear after a live resize, not only after reload.
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, timezone_id="Asia/Jakarta")
        page.route("**/data/dashboard-snapshot.json", lambda route: route.fulfill(json=snapshot))
        page.goto(URL, wait_until="networkidle")
        open_projects(page)
        page.set_viewport_size({"width": 1024, "height": 768})
        page.wait_for_timeout(250)
        assert page.locator(".active-calendar-pan-cue").count() >= 1, "pan cue did not react to live viewport resize"
        assert_no_document_overflow(page, "live-resize")
        page.close()
        browser.close()

    (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"project desktop matrix QA: {len(results)} viewports PASS")


if __name__ == "__main__":
    main()
