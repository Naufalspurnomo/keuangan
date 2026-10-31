#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'presensi-browser-qa'
EMPLOYEE_ID = 'pegawai-1'
PROJECT_ID = 'p26-griya'
LAT = -7.3546465
LON = 112.7826242


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def php_config() -> str:
    return f'''<?php
return [
  'username' => 'admin',
  'password_hash' => password_hash('browser-test-password', PASSWORD_DEFAULT),
  'proxy_token' => 'browser-test-token',
  'upstream_snapshot_url' => 'https://example.com/snapshot',
];
'''


def presensi_config() -> str:
    return f'''<?php
return [
  'retention_days' => 90,
  'employees' => [
    ['id' => 'pegawai-1', 'name' => 'Pegawai 1'],
    ['id' => 'pegawai-2', 'name' => 'Pegawai 2'],
    ['id' => 'pegawai-3', 'name' => 'Pegawai 3'],
  ],
  'projects' => [
    ['id' => '{PROJECT_ID}', 'name' => 'Griya Wellness Center', 'company' => 'Holla', 'active' => true],
  ],
];
'''


@contextlib.contextmanager
def server():
    subprocess.run(['python3', 'scripts/build_rumahweb_presensi_release.py'], cwd=ROOT, check=True)
    subprocess.run(['python3', 'scripts/build_rumahweb_admin_release.py'], cwd=ROOT, check=True)
    tmp = Path(tempfile.mkdtemp(prefix='hollawall-presensi-browser-'))
    public = tmp / 'public_html'
    public.mkdir()
    shutil.copytree(ROOT / 'artifacts' / 'rumahweb-presensi-release' / 'absen', public / 'absen')
    shutil.copytree(ROOT / 'artifacts' / 'rumahweb-admin-release' / 'admin', public / 'admin')
    (tmp / '.hollawall-admin.php').write_text(php_config(), encoding='utf-8')
    (tmp / '.hollawall-admin.php').chmod(0o600)
    (tmp / '.hollawall-presensi.php').write_text(presensi_config(), encoding='utf-8')
    (tmp / '.hollawall-presensi.php').chmod(0o600)
    port = free_port()
    env = {**os.environ, 'HOLLAWALL_ADMIN_CONFIG': str(tmp / '.hollawall-admin.php'), 'HOLLAWALL_PRESENSI_CONFIG': str(tmp / '.hollawall-presensi.php')}
    proc = subprocess.Popen(['php', '-S', f'127.0.0.1:{port}', '-t', str(public)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(50):
            try:
                requests.get(base + '/absen/api/bootstrap.php', timeout=.25)
                break
            except requests.RequestException:
                time.sleep(.1)
        yield base, tmp
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def assert_no_errors(errors: list[str]) -> None:
    assert not errors, errors


def fake_camera_file() -> Path:
    path = Path('/root/snap/chromium/common/hollawall-presensi-camera.y4m')
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 320, 240
    colors = [(242, 107, 45), (26, 163, 168), (247, 244, 238), (23, 32, 51)]
    y_plane = bytearray(width * height)
    u_plane = bytearray((width // 2) * (height // 2))
    v_plane = bytearray((width // 2) * (height // 2))
    def yuv(rgb):
        r, g, b = rgb
        return (
            max(0, min(255, round(.257 * r + .504 * g + .098 * b + 16))),
            max(0, min(255, round(-.148 * r - .291 * g + .439 * b + 128))),
            max(0, min(255, round(.439 * r - .368 * g - .071 * b + 128))),
        )
    converted = [yuv(color) for color in colors]
    for y in range(height):
        for x in range(width):
            band = min(3, x * 4 // width)
            luminance, _, _ = converted[band]
            if 90 < x < 230 and 65 < y < 175:
                luminance = min(235, luminance + 20)
            y_plane[y * width + x] = luminance
    for y in range(height // 2):
        for x in range(width // 2):
            band = min(3, x * 4 // (width // 2))
            _, u, v = converted[band]
            offset = y * (width // 2) + x
            u_plane[offset] = u
            v_plane[offset] = v
    frame = b'FRAME\n' + bytes(y_plane) + bytes(u_plane) + bytes(v_plane)
    path.write_bytes(f'YUV4MPEG2 W{width} H{height} F10:1 Ip A1:1 C420jpeg\n'.encode() + frame * 300)
    return path


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {'employee': {}, 'dashboard': {}, 'events': []}
    with server() as (base, account_root), sync_playwright() as p:
        camera = fake_camera_file()
        browser = p.chromium.launch(headless=True, executable_path='/snap/bin/chromium', args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', f'--use-file-for-fake-video-capture={camera}'])

        camera_denied = browser.new_context(viewport={'width': 320, 'height': 720}, geolocation={'latitude': LAT, 'longitude': LON, 'accuracy': 12}, permissions=['geolocation'])
        camera_denied.add_init_script("navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('denied', 'NotAllowedError'))")
        camera_page = camera_denied.new_page()
        camera_page.goto(base + '/absen/presensi/', wait_until='networkidle')
        camera_page.locator('#employee').select_option(EMPLOYEE_ID)
        camera_page.locator('#project').select_option(PROJECT_ID)
        camera_page.get_by_role('button', name='Aktifkan kamera').click()
        expect(camera_page.locator('#notice')).to_contain_text('Izin kamera ditolak', timeout=10000)
        assert camera_page.locator('#submit-presensi').is_disabled()
        assert camera_page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
        camera_page.screenshot(path=str(OUT / 'employee-camera-denied-320.png'), full_page=True)
        camera_denied.close()

        location_denied = browser.new_context(viewport={'width': 390, 'height': 844}, permissions=['camera'])
        location_denied.add_init_script("Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition: (_ok, fail) => fail({ code: 1, message: 'denied' }) } })")
        location_page = location_denied.new_page()
        location_page.goto(base + '/absen/presensi/', wait_until='networkidle')
        location_page.locator('#employee').select_option(EMPLOYEE_ID)
        location_page.locator('#project').select_option(PROJECT_ID)
        location_page.get_by_role('button', name='Aktifkan kamera').click()
        location_page.get_by_role('button', name='Ambil selfie & lokasi').click()
        expect(location_page.locator('#notice')).to_contain_text('Lokasi presisi tidak dapat dibaca', timeout=10000)
        assert location_page.locator('#submit-presensi').is_disabled()
        location_page.screenshot(path=str(OUT / 'employee-location-denied-390.png'), full_page=True)
        location_denied.close()
        results['denial_paths'] = {'camera_320': 'PASS', 'location_390': 'PASS'}

        context = browser.new_context(
            viewport={'width': 390, 'height': 844},
            geolocation={'latitude': LAT, 'longitude': LON, 'accuracy': 12},
            permissions=['camera', 'geolocation'],
        )
        page = context.new_page()
        errors: list[str] = []
        page.on('console', lambda msg: errors.append(f'console:{msg.type}:{msg.text}') if msg.type == 'error' else None)
        page.on('pageerror', lambda exc: errors.append(f'page:{exc}'))
        page.on('requestfailed', lambda req: errors.append(f'request:{req.url}:{req.failure}'))
        page.goto(base + '/absen/presensi/', wait_until='networkidle')
        assert page.get_by_role('heading', name='Presensi proyek, langsung dari lokasi.').is_visible()
        assert page.locator('#submit-presensi').is_disabled()
        assert page.locator('#employee option').all_text_contents() == ['Pilih pegawai', 'Pegawai 1', 'Pegawai 2', 'Pegawai 3']
        assert page.locator('#project option').all_text_contents() == ['Pilih proyek', 'Griya Wellness Center · Holla']
        page.locator('#employee').select_option(EMPLOYEE_ID)
        page.locator('#project').select_option(PROJECT_ID)
        page.get_by_role('button', name='Aktifkan kamera').click()
        page.get_by_role('button', name='Ambil selfie & lokasi').click()
        expect(page.locator('#submit-presensi')).to_be_enabled(timeout=20000)
        assert 'Akurasi' in page.locator('#location-detail').inner_text()
        page.screenshot(path=str(OUT / 'employee-proof-ready-390.png'), full_page=True)
        page.set_viewport_size({'width': 320, 'height': 720})
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
        assert page.locator('#employee').evaluate('(node) => node.getBoundingClientRect().height >= 44')
        assert page.locator('#submit-presensi').evaluate('(node) => node.getBoundingClientRect().height >= 44')
        page.screenshot(path=str(OUT / 'employee-proof-ready-320.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('button', name='Kirim Check-in').click()
        expect(page.locator('#notice')).to_contain_text('berhasil', ignore_case=True, timeout=20000)
        page.screenshot(path=str(OUT / 'employee-mobile-checkin.png'), full_page=True)
        event_path = account_root / '.hollawall-presensi' / 'events.json'
        qa_events = json.loads(event_path.read_text(encoding='utf-8'))
        qa_events[0]['occurred_at'] = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(time.time() - 3900))
        event_path.write_text(json.dumps(qa_events, indent=2) + '\n', encoding='utf-8')
        event_path.chmod(0o600)

        expect(page.locator('#action')).to_have_value('check_out', timeout=20000)
        assert page.locator('#project').input_value() == PROJECT_ID
        assert page.locator('#project').is_disabled()
        page.get_by_role('button', name='Aktifkan kamera').click()
        page.get_by_role('button', name='Ambil selfie & lokasi').click()
        expect(page.locator('#submit-presensi')).to_be_enabled(timeout=20000)
        page.get_by_role('button', name='Kirim Check-out').click()
        expect(page.locator('#notice')).to_contain_text('berhasil', ignore_case=True, timeout=20000)
        results['employee'] = {'mobile_320': 'PASS', 'mobile_390': 'PASS', 'camera_required': True, 'location_required': True, 'proof_ready': 'PASS', 'check_in': 'PASS', 'check_out': 'PASS', 'overflow': page.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth')}
        assert results['employee']['overflow'] is False
        assert_no_errors(errors)

        admin = context.new_page()
        admin_errors: list[str] = []
        admin.on('console', lambda msg: admin_errors.append(f'console:{msg.type}:{msg.text}') if msg.type == 'error' else None)
        admin.on('pageerror', lambda exc: admin_errors.append(f'page:{exc}'))
        admin.on('requestfailed', lambda req: admin_errors.append(f'request:{req.url}:{req.failure}'))
        admin.set_viewport_size({'width': 1440, 'height': 1000})
        admin.goto(base + '/admin/', wait_until='domcontentloaded')
        admin.get_by_label('Username').fill('admin')
        admin.get_by_label('Password').fill('browser-test-password')
        admin.get_by_role('button', name='Masuk').click()
        admin.wait_for_load_state('networkidle')
        admin.goto(base + '/admin/#projects?project=' + PROJECT_ID, wait_until='networkidle')
        transaction_tab = admin.get_by_role('tab', name='Transaksi', selected=True)
        assert transaction_tab.is_visible()
        transaction_tab.focus()
        transaction_tab.press('End')
        expect(admin.get_by_role('tab', name='Presensi', selected=True)).to_be_focused()
        admin.get_by_role('tab', name='Presensi').press('Home')
        expect(admin.get_by_role('tab', name='Transaksi', selected=True)).to_be_focused()
        admin.get_by_role('tab', name='Transaksi').press('ArrowRight')
        expect(admin.get_by_role('tab', name='Presensi', selected=True)).to_be_focused()
        admin.wait_for_selector('text=Pegawai 1')
        results['keyboard_tabs'] = 'PASS'
        assert admin.get_by_text('Selesai', exact=True).count() >= 1
        assert admin.locator('.presensi-evidence img').count() == 2
        assert admin.get_by_role('link', name='Buka lokasi Check-in Pegawai 1 di peta').get_attribute('href') == 'https://www.google.com/maps?q=-7.354647%2C112.782624'
        assert admin.get_by_text('-7.354647, 112.782624', exact=True).count() == 2
        for index in range(2):
            assert admin.locator('.presensi-evidence img').nth(index).evaluate('(img) => img.complete && img.naturalWidth > 0')
        admin.screenshot(path=str(OUT / 'dashboard-desktop-presensi.png'), full_page=True)
        admin.set_viewport_size({'width': 390, 'height': 844})
        admin.reload(wait_until='networkidle')
        admin.get_by_role('tab', name='Presensi').click()
        admin.wait_for_selector('text=Pegawai 1')
        overflow = admin.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth')
        assert overflow is False
        assert admin.locator('.project-detail-back').evaluate('(node) => node.getBoundingClientRect().height >= 44')
        assert admin.locator('.project-detail-filter .command-search').evaluate('(node) => node.getBoundingClientRect().height >= 44')
        assert admin.locator('.project-detail-tabs [role="tab"]').first.evaluate('(node) => node.getBoundingClientRect().height >= 44')
        admin.screenshot(path=str(OUT / 'dashboard-mobile-presensi.png'), full_page=True)
        assert_no_errors(admin_errors)
        results['dashboard'] = {'default_transactions': True, 'presensi_tab': 'PASS', 'selfies': 2, 'desktop': 'PASS', 'mobile': 'PASS', 'touch_targets_44px': True, 'overflow': overflow}
        event_file = next((Path(admin.url).parent for _ in []), None)
        results['events'] = ['check_in', 'check_out']
        context.close()
        browser.close()
        camera.unlink(missing_ok=True)
    (OUT / 'QA.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    run()
