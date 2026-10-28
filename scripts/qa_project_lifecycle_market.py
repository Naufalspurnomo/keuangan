#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.getenv("QA_URL", "http://127.0.0.1:4173/")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "project-lifecycle-market-qa"
OUT.mkdir(parents=True, exist_ok=True)

viewports = (
    ("desktop-1440", 1440, 900),
    ("laptop-1024", 1024, 768),
    ("mobile-390", 390, 844),
)
results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path="/snap/bin/chromium", args=["--no-sandbox"])
    for name, width, height in viewports:
        page = browser.new_page(viewport={"width": width, "height": height})
        console_errors: list[str] = []
        page_errors: list[str] = []
        request_failures: list[str] = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: request_failures.append(f"{request.method} {request.url}: {request.failure}"))

        page.goto(URL, wait_until="networkidle")
        if width <= 760:
            page.get_by_role("button", name="Buka navigasi").click()
        page.get_by_role("button", name="Proyek", exact=True).click()
        page.get_by_role("heading", name="Umur dan status proyek").wait_for()

        canvases = page.locator(".project-market-canvas")
        assert canvases.count() == 4, (name, canvases.count())
        companies = canvases.evaluate_all("els => els.map(el => el.dataset.projectCompany)")
        assert companies == ["Holla", "Hojja", "Texturin Bali", "Texturin Surabaya"], (name, companies)
        assert page.locator(".project-market-month").count() == 48, (name, "month axis")
        assert page.locator('[aria-label="Halaman chart"]').count() == 0, (name, "chart pagination remains")
        assert page.locator(".year-candle-board").count() == 0, (name, "legacy chart remains")

        summaries = page.locator(".project-market-summary strong").all_text_contents()
        assert len(summaries) == 4 and all(re.fullmatch(r"\d+ / \d+", value.strip()) for value in summaries), (name, summaries)
        candles = page.locator("[data-project-candle]")
        assert candles.count() == 28, (name, candles.count())

        # DOM order and rendered X position must progress from old to new in every non-empty company.
        order_checks = page.locator(".project-market-canvas").evaluate_all("""canvases => canvases.map(canvas => {
          const marks = [...canvas.querySelectorAll('[data-project-candle]')];
          const xs = marks.map(mark => mark.getBoundingClientRect().x);
          return { company: canvas.dataset.projectCompany, count: marks.length, ordered: xs.every((x, index) => index === 0 || x >= xs[index - 1]) };
        })""")
        assert all(item["ordered"] for item in order_checks), (name, order_checks)

        viewport = canvases.first.locator(".project-market-viewport")
        viewport.scroll_into_view_if_needed()
        before_zoom = canvases.first.locator(".project-market-chart").get_attribute("style")
        page.get_by_role("button", name="Perbesar semua chart").click()
        page.wait_for_timeout(100)
        after_zoom = canvases.first.locator(".project-market-chart").get_attribute("style")
        assert before_zoom != after_zoom, (name, "zoom did not change geometry")
        assert page.get_by_text("Zoom 120%", exact=True).is_visible(), (name, "zoom readout")

        # Panning must work in both axes once zoom creates overflow.
        dimensions = viewport.evaluate("el => ({left: el.scrollLeft, top: el.scrollTop, maxX: el.scrollWidth - el.clientWidth, maxY: el.scrollHeight - el.clientHeight})")
        viewport.evaluate("el => { el.scrollLeft = Math.min(80, el.scrollWidth - el.clientWidth); el.scrollTop = Math.min(60, el.scrollHeight - el.clientHeight); }")
        box = viewport.bounding_box()
        assert box
        page.mouse.move(box["x"] + min(250, box["width"] * .7), box["y"] + min(240, box["height"] * .6))
        page.mouse.down()
        page.mouse.move(box["x"] + 120, box["y"] + 120, steps=5)
        page.mouse.up()
        page.wait_for_timeout(80)
        after_pan = viewport.evaluate("el => ({left: el.scrollLeft, top: el.scrollTop})")
        assert dimensions["maxX"] > 0 and dimensions["maxY"] > 0, (name, dimensions)
        assert after_pan["left"] >= 0 and after_pan["top"] >= 0, (name, after_pan)

        page.get_by_role("button", name="Kembali ke proyek terbaru Holla").click()
        page.wait_for_timeout(80)
        latest = viewport.evaluate("el => ({left: el.scrollLeft, max: el.scrollWidth - el.clientWidth, rightGap: el.scrollWidth - el.clientWidth - el.scrollLeft})")
        # stable both-edges reserves one scrollbar gutter at the right edge (about 20px).
        assert latest["rightGap"] <= 24, (name, latest)
        axis_box = canvases.first.locator('.project-market-month b').first.bounding_box()
        viewport_box = viewport.bounding_box()
        assert axis_box and viewport_box
        assert axis_box['x'] >= viewport_box['x'] - 2, (name, 'month axis left viewport')
        assert axis_box['x'] <= viewport_box['x'] + 74, (name, 'month axis not sticky')

        page.get_by_role("button", name="Reset tampilan semua chart").click()
        page.wait_for_timeout(100)
        assert page.get_by_text("Zoom 100%", exact=True).is_visible(), (name, "reset zoom")
        assert viewport.evaluate("el => el.scrollTop") == 0, (name, "reset vertical pan")

        body_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
        assert not body_overflow, (name, "document horizontal overflow")
        assert not console_errors, (name, console_errors)
        assert not page_errors, (name, page_errors)
        assert not request_failures, (name, request_failures)

        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        results.append({
            "viewport": name,
            "canvases": 4,
            "candles": candles.count(),
            "summaries": summaries,
            "month_markers": page.locator(".project-market-month").count(),
            "zoom": "PASS",
            "pan_x_y": "PASS",
            "latest": "PASS",
            "reset": "PASS",
            "document_overflow": False,
            "console_errors": 0,
            "page_errors": 0,
            "request_failures": 0,
        })
        page.close()
    browser.close()

(OUT / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps({"status": "PASS", "viewports": len(results), "results": results}, indent=2))
