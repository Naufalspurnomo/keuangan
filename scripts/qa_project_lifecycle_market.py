#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.getenv("QA_URL", "http://127.0.0.1:4173/")
ENGINE = os.getenv("QA_ENGINE", "chromium")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "project-lifecycle-market-qa" / ENGINE
OUT.mkdir(parents=True, exist_ok=True)

viewports = (
    ("desktop-1440", 1440, 900),
    ("laptop-1024", 1024, 768),
    ("desktop-boundary-901", 901, 700),
    ("mobile-boundary-900", 900, 700),
    ("mobile-390", 390, 844),
)
results = []
companies = ["Holla", "Hojja", "Texturin Bali", "Texturin Surabaya"]
expected_id_count = 0

def active_year_geometry(page):
    return page.locator(".year-command nav").evaluate("el => { const active=el.querySelector('button.active'); const n=el.getBoundingClientRect(); const a=active.getBoundingClientRect(); return {navLeft:n.left,navRight:n.right,activeLeft:a.left,activeRight:a.right}; }")

def assert_active_year_visible(page, label):
    geometry = active_year_geometry(page)
    assert geometry["activeLeft"] >= geometry["navLeft"] - 1 and geometry["activeRight"] <= geometry["navRight"] + 1, (label, "active year clipped", geometry)


def assert_month_axis_geometry(page, label):
    canvases = page.locator(".project-market-canvas")
    assert canvases.count() == 4, (label, "canvas count", canvases.count())
    for index in range(canvases.count()):
        canvas_locator = canvases.nth(index)
        canvas_locator.evaluate("el => el.scrollIntoView({block: 'start'})")
        page.wait_for_timeout(40)
        canvas = canvas_locator.evaluate("""canvas => {
          const viewport = canvas.querySelector('.project-market-viewport').getBoundingClientRect();
          const axis = canvas.querySelector('.project-market-axis');
          const previousPointerEvents = axis.style.pointerEvents;
          axis.style.pointerEvents = 'auto';
          const monthBoxes = [...canvas.querySelectorAll('.project-market-month b')].map(el => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            const visible = rect.bottom > Math.max(viewport.top, 0)
              && rect.top < Math.min(viewport.bottom, window.innerHeight)
              && rect.right > 0
              && rect.left < window.innerWidth;
            const topmost = visible ? document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2) : null;
            return {
              top: rect.top,
              bottom: rect.bottom,
              left: rect.left,
              right: rect.right,
              z: Number(style.zIndex || 0),
              visible,
              labelIsTopmost: !visible || topmost === el || el.contains(topmost),
            };
          });
          const visibleMonthBoxes = monthBoxes.filter(box => box.visible);
          axis.style.pointerEvents = previousPointerEvents;
          return { company: canvas.dataset.projectCompany, monthBoxes, visibleMonthBoxes };
        }""")
        month_boxes = canvas["monthBoxes"]
        assert len(month_boxes) == 12, (label, canvas["company"], "month count", len(month_boxes))
        assert canvas["visibleMonthBoxes"], (label, canvas["company"], "no visible month labels; layer assertion would be vacuous")
        assert all(box["z"] >= 10 for box in month_boxes), (label, canvas["company"], "month z-index", month_boxes)
        assert all(month_boxes[position + 1]["top"] - month_boxes[position]["top"] >= 24 for position in range(len(month_boxes) - 1)), (label, canvas["company"], "month spacing", month_boxes)
        assert all(box["labelIsTopmost"] for box in month_boxes), (label, canvas["company"], "visible month label covered by candle", month_boxes)

with sync_playwright() as p:
    if ENGINE == "chromium":
        browser = p.chromium.launch(headless=True, executable_path="/snap/bin/chromium", args=["--no-sandbox"])
    elif ENGINE == "firefox":
        browser = p.firefox.launch(headless=True)
    elif ENGINE == "webkit":
        browser = p.webkit.launch(headless=True)
    else:
        raise ValueError(f"Unsupported QA_ENGINE: {ENGINE}")
    for name, width, height in viewports:
        page = browser.new_page(viewport={"width": width, "height": height})
        console_errors: list[str] = []
        page_errors: list[str] = []
        request_failures: list[str] = []
        page.add_init_script("localStorage.removeItem('hollawall-finance-demo-v3')")
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: request_failures.append(f"{request.method} {request.url}: {request.failure}"))

        page.goto(URL, wait_until="networkidle")
        if width <= 900:
            page.get_by_role("button", name="Buka navigasi").click()
        page.get_by_role("button", name="Proyek", exact=True).click()
        page.get_by_role("heading", name="Umur dan status proyek").wait_for()
        assert_active_year_visible(page, name)

        canvases = page.locator(".project-market-canvas")
        assert canvases.count() == 4, (name, canvases.count())
        rendered_companies = canvases.evaluate_all("els => els.map(el => el.dataset.projectCompany)")
        assert rendered_companies == companies, (name, rendered_companies)
        month_marker_count = page.locator(".project-market-month").count()
        assert month_marker_count == 48, (name, "month axis")
        assert_month_axis_geometry(page, name)
        assert page.locator('[aria-label="Halaman chart"]').count() == 0, (name, "chart pagination remains")
        assert page.locator(".year-candle-board").count() == 0, (name, "legacy chart remains")

        summaries = page.locator(".project-market-summary strong").all_text_contents()
        assert len(summaries) == 4 and all(re.fullmatch(r"\d+ / \d+", value.strip()) for value in summaries), (name, summaries)
        candles = page.locator("[data-project-candle]")
        candle_count = candles.count()
        seeded = json.loads(page.evaluate("localStorage.getItem('hollawall-finance-demo-v3')"))
        assert seeded["version"] == 3 and len(seeded["projects"]) >= 36
        assert len({project["name"] for project in seeded["projects"]}) == len(seeded["projects"])
        assert {project["started_on"][:4] for project in seeded["projects"]} == {"2024", "2025", "2026"}
        snapshot = seeded["updated_at"][:10]
        expected_projects = [project for project in seeded["projects"] if project["started_on"] <= "2026-12-31" and (project["completed_on"] or (project["started_on"] if project["status"] == "planned" else snapshot)) >= "2026-01-01"]
        expected_ids = [project["id"] for project in expected_projects]
        expected_by_company = {company: sorted(project["id"] for project in expected_projects if project["company"] == company) for company in companies}
        expected_id_count = len(expected_ids)
        rendered_ids = sorted(candles.evaluate_all("els => els.map(el => el.dataset.projectId)"))
        assert rendered_ids == sorted(expected_ids), (name, rendered_ids, expected_ids)
        for company in companies:
            company_ids = sorted(page.locator(f'[data-project-company="{company}"] [data-project-id]').evaluate_all("els => els.map(el => el.dataset.projectId)"))
            assert company_ids == expected_by_company[company], (name, company, company_ids, expected_by_company[company])

        # Registry pagination is independent; all four full-year lifecycle canvases remain unchanged.
        registry_pagination = page.get_by_role("navigation", name="Pagination proyek")
        assert registry_pagination.is_visible(), (name, "registry pagination missing")
        assert registry_pagination.get_by_text("Halaman 1 / 2").is_visible(), (name, "initial registry page")
        registry_page_one = page.locator(".project-register article .project-register-main strong").all_text_contents()
        page.get_by_role("button", name="Halaman proyek berikutnya").click()
        assert registry_pagination.get_by_text("Halaman 2 / 2").is_visible(), (name, "next registry page")
        registry_page_two = page.locator(".project-register article .project-register-main strong").all_text_contents()
        assert registry_page_two and registry_page_two != registry_page_one, (name, "registry page did not change")
        assert canvases.count() == 4 and page.locator("[data-project-candle]").count() == candle_count, (name, "registry pagination changed lifecycle canvases")

        # DOM order and rendered X position must progress from old to new in every non-empty company.
        order_checks = page.locator(".project-market-canvas").evaluate_all("""canvases => canvases.map(canvas => {
          const marks = [...canvas.querySelectorAll('[data-project-candle]')];
          const xs = marks.map(mark => mark.getBoundingClientRect().x);
          return { company: canvas.dataset.projectCompany, count: marks.length, ordered: xs.every((x, index) => index === 0 || x >= xs[index - 1]) };
        })""")
        assert all(item["ordered"] for item in order_checks), (name, order_checks)

        viewport = canvases.first.locator(".project-market-viewport")
        viewport.scroll_into_view_if_needed()
        before_zoom = page.locator(".project-market-chart").evaluate_all("els => els.map(el => el.getAttribute('style'))")
        page.get_by_role("button", name="Perbesar semua chart").click()
        page.wait_for_timeout(100)
        after_zoom = page.locator(".project-market-chart").evaluate_all("els => els.map(el => el.getAttribute('style'))")
        assert all(before_zoom[index] != after_zoom[index] for index in range(4)), (name, "global zoom did not change all geometry")
        zoom_readouts = page.locator(".project-market-toolbar > span").all_text_contents()
        assert all("zoom 120%" in value.lower() for value in zoom_readouts), (name, "zoom readout", zoom_readouts)

        # Ordinary wheel zooms only the hovered canvas; Shift+wheel pans it horizontally.
        if width > 580:
            wheel_box = viewport.bounding_box()
            assert wheel_box
            other_geometry = page.locator(".project-market-viewport").evaluate_all("els => els.slice(1).map(el => ({left: el.scrollLeft, top: el.scrollTop, width: el.querySelector('.project-market-chart').getBoundingClientRect().width}))")
            visible_wheel_y = min(wheel_box["y"] + min(160, wheel_box["height"] * .45), height - 20)
            page.mouse.move(wheel_box["x"] + wheel_box["width"] * .65, visible_wheel_y)
            page_top_before = page.evaluate("window.scrollY")
            page.mouse.wheel(0, -100)
            page.wait_for_timeout(100)
            local_readout = canvases.first.locator(".project-market-toolbar > span").inner_text()
            assert "zoom 138%" in local_readout.lower(), (name, "ordinary wheel did not zoom active canvas in", local_readout)
            assert page.evaluate("window.scrollY") == page_top_before, (name, "canvas wheel moved page")
            page.mouse.wheel(0, 100)
            page.wait_for_timeout(100)
            local_readout = canvases.first.locator(".project-market-toolbar > span").inner_text()
            assert "zoom 120%" in local_readout.lower(), (name, "ordinary wheel did not zoom active canvas out", local_readout)
            other_after_wheel = page.locator(".project-market-viewport").evaluate_all("els => els.slice(1).map(el => ({left: el.scrollLeft, top: el.scrollTop, width: el.querySelector('.project-market-chart').getBoundingClientRect().width}))")
            assert other_after_wheel == other_geometry, (name, "local wheel changed sibling canvas", other_geometry, other_after_wheel)

            # Create horizontal overflow locally before proving Shift+wheel pan.
            page.mouse.wheel(0, -300)
            page.wait_for_timeout(100)
            assert "zoom 183%" in canvases.first.locator(".project-market-toolbar > span").inner_text().lower(), (name, "local overflow zoom", canvases.first.locator(".project-market-toolbar > span").inner_text())
            assert viewport.evaluate("el => el.scrollWidth > el.clientWidth"), (name, "local zoom did not create horizontal overflow")
            viewport.evaluate("el => { el.scrollLeft = 0 }")
            horizontal_left = viewport.evaluate("el => el.scrollLeft")
            page.keyboard.down("Shift")
            page.mouse.wheel(0, 80)
            page.keyboard.up("Shift")
            page.wait_for_timeout(100)
            assert viewport.evaluate("el => el.scrollLeft") != horizontal_left, (name, "Shift+wheel did not pan horizontally")
            assert "zoom 183%" in canvases.first.locator(".project-market-toolbar > span").inner_text().lower(), (name, "Shift+wheel changed zoom")
            viewport.evaluate("el => { el.scrollLeft = Math.min(120, el.scrollWidth - el.clientWidth) }")
            dominant_x_left = viewport.evaluate("el => el.scrollLeft")
            page.mouse.wheel(-80, 0)
            page.wait_for_timeout(100)
            assert viewport.evaluate("el => el.scrollLeft") != dominant_x_left, (name, "dominant-X wheel did not pan horizontally")
            assert "zoom 183%" in canvases.first.locator(".project-market-toolbar > span").inner_text().lower(), (name, "dominant-X wheel changed zoom")

            report_head = page.locator(".project-market-report-head")
            report_head.scroll_into_view_if_needed()
            head_box = report_head.bounding_box()
            assert head_box
            page.mouse.move(head_box["x"] + min(40, head_box["width"] / 2), head_box["y"] + min(40, head_box["height"] / 2))
            outside_top = page.evaluate("window.scrollY")
            page.mouse.wheel(0, 100)
            page.wait_for_timeout(100)
            assert page.evaluate("window.scrollY") > outside_top, (name, "wheel outside canvas did not scroll page")
            assert "zoom 183%" in canvases.first.locator(".project-market-toolbar > span").inner_text().lower(), (name, "outside wheel changed canvas zoom")
            viewport.scroll_into_view_if_needed()

        # Panning must work in both axes once zoom creates overflow.
        dimensions = viewport.evaluate("el => ({left: el.scrollLeft, top: el.scrollTop, maxX: el.scrollWidth - el.clientWidth, maxY: el.scrollHeight - el.clientHeight})")
        viewport.evaluate("el => { el.scrollLeft = Math.min(80, el.scrollWidth - el.clientWidth); el.scrollTop = Math.min(60, el.scrollHeight - el.clientHeight); }")
        siblings_before_pan = page.locator(".project-market-viewport").evaluate_all("els => els.slice(1).map(el => ({left: el.scrollLeft, top: el.scrollTop}))")
        box = viewport.bounding_box()
        assert box
        page.mouse.move(box["x"] + min(250, box["width"] * .7), box["y"] + min(240, box["height"] * .6))
        page.mouse.down()
        page.mouse.move(box["x"] + 120, box["y"] + 120, steps=5)
        page.mouse.up()
        page.wait_for_timeout(80)
        after_pan = viewport.evaluate("el => ({left: el.scrollLeft, top: el.scrollTop})")
        assert dimensions["maxX"] >= 0 and dimensions["maxY"] > 0, (name, dimensions)
        assert after_pan["left"] >= 0 and after_pan["top"] >= 0, (name, after_pan)
        siblings_after_pan = page.locator(".project-market-viewport").evaluate_all("els => els.slice(1).map(el => ({left: el.scrollLeft, top: el.scrollTop}))")
        assert siblings_after_pan == siblings_before_pan, (name, "local drag changed sibling canvas", siblings_before_pan, siblings_after_pan)
        horizontal_pan = "PASS" if dimensions["maxX"] > 0 else "FIT"
        if dimensions["maxX"] > 0:
            page.get_by_role("button", name="Kembali ke proyek terbaru Holla").click()
            page.wait_for_timeout(80)
            viewport.scroll_into_view_if_needed()
            candle_box = canvases.first.locator("[data-project-candle]").last.bounding_box()
            viewport_box = viewport.bounding_box()
            assert candle_box and viewport_box
            candle_x = candle_box["x"] + candle_box["width"] / 2
            candle_y = max(viewport_box["y"] + 20, min(candle_box["y"] + candle_box["height"] / 2, viewport_box["y"] + viewport_box["height"] - 20, height - 20))
            before_candle_pan = viewport.evaluate("el => el.scrollLeft")
            page.mouse.move(candle_x, candle_y)
            page.mouse.down()
            page.mouse.move(candle_x + 45, candle_y, steps=5)
            page.mouse.up()
            page.wait_for_timeout(80)
            assert viewport.evaluate("el => el.scrollLeft") != before_candle_pan, (name, "candle drag did not pan")
            assert page.get_by_role("heading", name="Umur dan status proyek").is_visible(), (name, "candle drag opened project")

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
        reset_readouts = page.locator(".project-market-toolbar > span").all_text_contents()
        assert all("zoom 100%" in value.lower() for value in reset_readouts), (name, "reset zoom", reset_readouts)
        assert viewport.evaluate("el => el.scrollTop") == 0, (name, "reset vertical pan")
        if width > 580:
            viewport.evaluate("el => el.scrollIntoView({ block: 'center', inline: 'nearest' })")
            page.wait_for_timeout(80)
            mid_scroll = viewport.evaluate("el => { const max = el.scrollHeight - el.clientHeight; el.scrollTop = max / 2; return { top: el.scrollTop, max }; }")
            wheel_box = viewport.bounding_box()
            assert wheel_box and mid_scroll["max"] > 2
            page.mouse.move(wheel_box["x"] + wheel_box["width"] * .65, min(wheel_box["y"] + 160, height - 20))
            min_page_top = page.evaluate("window.scrollY")
            page.mouse.wheel(0, 100)
            page.wait_for_timeout(100)
            assert "zoom 100%" in canvases.first.locator(".project-market-toolbar > span").inner_text().lower(), (name, "minimum wheel exceeded zoom bound")
            assert viewport.evaluate("el => el.scrollTop") == mid_scroll["top"], (name, "ordinary wheel panned canvas vertically")
            assert page.evaluate("window.scrollY") == min_page_top, (name, "canvas wheel moved page at minimum zoom")

            for _ in range(5):
                page.get_by_role("button", name="Perbesar semua chart").click()
            max_readouts = page.locator(".project-market-toolbar > span").all_text_contents()
            assert all("zoom 240%" in value.lower() for value in max_readouts), (name, "maximum zoom", max_readouts)
            viewport.evaluate("el => { el.scrollTop = 120 }")
            max_top = viewport.evaluate("el => el.scrollTop")
            wheel_box = viewport.bounding_box()
            assert wheel_box
            page.mouse.move(wheel_box["x"] + wheel_box["width"] * .65, min(wheel_box["y"] + 160, height - 20))
            max_page_top = page.evaluate("window.scrollY")
            page.mouse.wheel(0, -100)
            page.wait_for_timeout(100)
            assert "zoom 240%" in canvases.first.locator(".project-market-toolbar > span").inner_text().lower(), (name, "maximum wheel exceeded zoom bound")
            assert viewport.evaluate("el => el.scrollTop") == max_top, (name, "ordinary wheel panned canvas vertically at maximum zoom")
            assert page.evaluate("window.scrollY") == max_page_top, (name, "canvas wheel moved page at maximum zoom")
            page.get_by_role("button", name="Reset tampilan semua chart").click()
            page.wait_for_timeout(100)

        click_candle = canvases.first.locator("[data-project-id]").last
        click_project_id = click_candle.get_attribute("data-project-id")
        click_candle.scroll_into_view_if_needed()
        page.wait_for_timeout(50)
        source_scroll = page.evaluate("window.scrollY")
        click_candle.click()
        page.get_by_role("button", name="Kembali ke Proyek").wait_for()
        assert page.evaluate("window.location.hash") == f"#projects?project={click_project_id}", (name, "project detail route", click_project_id, page.evaluate("window.location.hash"))
        page.go_back(wait_until="networkidle")
        page.get_by_role("heading", name="Umur dan status proyek").wait_for()
        assert page.evaluate("window.location.hash") == "#projects", (name, "browser back did not restore projects")
        page.wait_for_function("top => Math.abs(window.scrollY - top) <= 2", arg=source_scroll, timeout=2_000)
        assert abs(page.evaluate("window.scrollY") - source_scroll) <= 2, (name, "browser back did not restore project scroll", source_scroll, page.evaluate("window.scrollY"))

        body_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
        assert not body_overflow, (name, "document horizontal overflow")
        assert not console_errors, (name, console_errors)
        assert not page_errors, (name, page_errors)
        assert not request_failures, (name, request_failures)

        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        results.append({
            "viewport": name,
            "canvases": 4,
            "candles": candle_count,
            "summaries": summaries,
            "month_markers": month_marker_count,
            "zoom": "PASS",
            "pan_x_y": horizontal_pan,
            "latest": "PASS",
            "reset": "PASS",
            "page_scroll_containment": "PASS",
            "project_back_navigation": "PASS",
            "document_overflow": False,
            "console_errors": 0,
            "page_errors": 0,
            "request_failures": 0,
        })
        page.close()

    resize_page = browser.new_page(viewport={"width": 1440, "height": 900})
    resize_page.add_init_script("localStorage.removeItem('hollawall-finance-demo-v3')")
    resize_page.goto(URL, wait_until="networkidle")
    resize_page.get_by_role("button", name="Proyek", exact=True).click()
    resize_page.get_by_role("heading", name="Umur dan status proyek").wait_for()
    resize_page.set_viewport_size({"width": 390, "height": 844})
    resize_page.wait_for_timeout(150)
    assert_active_year_visible(resize_page, "desktop-to-mobile resize")
    resize_page.locator(".topbar-add").click()
    dialog = resize_page.get_by_role("dialog")
    dialog.get_by_label("Nama proyek *").fill("Year Growth Probe")
    dialog.get_by_label("Tanggal mulai *").fill("2023-12-20")
    dialog.get_by_role("button", name="Tambah proyek").click()
    dialog.wait_for(state="detached")
    resize_page.wait_for_timeout(150)
    assert_active_year_visible(resize_page, "year-list growth")
    resize_page.close()
    browser.close()

(OUT / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps({"status": "PASS", "engine": ENGINE, "viewports": len(results), "responsive_reconciliation": "PASS", "exact_candle_ids": expected_id_count, "results": results}, indent=2))
