import contextlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import unittest
import zlib
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
ABSEN_RELEASE = ROOT / "artifacts" / "rumahweb-presensi-release" / "absen"
ADMIN_RELEASE = ROOT / "artifacts" / "rumahweb-admin-release" / "admin"


def proof_png(width: int = 640, height: int = 480, solid: tuple[int, int, int] | None = None) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(solid or ((x * 17 + y * 11) % 256, (x * 7 + y * 19) % 256, (x * 23 + y * 3) % 256))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    padding = chunk(b"tEXt", b"proof=" + bytes((index * 73) % 256 for index in range(2048))) if solid else b""
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + padding + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")


class PresensiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["python3", "scripts/build_rumahweb_presensi_release.py"], cwd=ROOT, check=True)
        subprocess.run(["python3", "scripts/build_rumahweb_admin_release.py"], cwd=ROOT, check=True)
        cls.username = "presensi-admin"
        cls.password = "synthetic-presensi-proof"
        cls.password_hash = subprocess.check_output(["php", "-r", f"echo password_hash('{cls.password}', PASSWORD_DEFAULT);"], text=True)
        cls.selfie = proof_png()
        assert len(cls.selfie) > 8192

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="hollawall-presensi-test-")
        self.account_root = Path(self._tmp.name)
        self.web_root = self.account_root / "public_html"
        shutil.copytree(ABSEN_RELEASE, self.web_root / "absen")
        shutil.copytree(ADMIN_RELEASE, self.web_root / "admin")
        self.config = self.account_root / ".hollawall-admin.php"
        self.config.write_text(
            "<?php return ["
            f"'username'=>'{self.username}',"
            f"'password_hash'=>'{self.password_hash}',"
            "'proxy_token'=>'synthetic-presensi-upstream-token',"
            "'upstream_snapshot_url'=>'https://example.invalid/snapshot'];",
            encoding="utf-8",
        )
        self.config.chmod(0o600)
        self.presensi_config = self.account_root / ".hollawall-presensi.php"
        project = "['id'=>'p26-griya','name'=>'Griya Wellness Center','company'=>'Holla','location_label'=>'Lokasi uji','latitude'=>-7.3546465,'longitude'=>112.7826242,'radius_m'=>150,'max_accuracy_m'=>75,'active'=>true]"
        other = "['id'=>'p26-fajar','name'=>'Fajar Distribution Hub','company'=>'Texturin Surabaya','location_label'=>'Lokasi uji','latitude'=>-7.3546465,'longitude'=>112.7826242,'radius_m'=>150,'max_accuracy_m'=>75,'active'=>true]"
        self.presensi_config.write_text("<?php return ['retention_days'=>90,'employees'=>[['id'=>'pegawai-1','name'=>'Pegawai 1'],['id'=>'pegawai-2','name'=>'Pegawai 2'],['id'=>'pegawai-3','name'=>'Pegawai 3']],'projects'=>[" + project + "," + other + "]];", encoding="utf-8")
        self.presensi_config.chmod(0o600)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @contextlib.contextmanager
    def server(self, fault: str | None = None, auto_start: bool = False):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "HOLLAWALL_ADMIN_CONFIG": str(self.config), "HOLLAWALL_PRESENSI_CONFIG": str(self.presensi_config)}
        if fault:
            env["HOLLAWALL_PRESENSI_FAULT"] = fault
        command = ["php"]
        if auto_start:
            command.extend(["-d", "session.auto_start=1"])
        command.extend(["-S", f"127.0.0.1:{port}", "-t", str(self.web_root)])
        process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        origin = f"http://127.0.0.1:{port}"
        try:
            for _ in range(50):
                try:
                    requests.get(origin + "/absen/presensi/", timeout=0.25)
                    break
                except requests.RequestException:
                    time.sleep(0.05)
            else:
                self.fail("PHP test server did not become ready")
            yield origin
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    @staticmethod
    def csrf_from(html: str) -> str:
        match = re.search(r'name="csrf" value="([^"]+)"', html)
        if not match:
            raise AssertionError("CSRF token missing")
        return match.group(1)

    def public_bootstrap(self, origin: str):
        response = requests.get(origin + "/absen/api/bootstrap.php", timeout=5)
        self.assertEqual(response.status_code, 200, response.text)
        session_id = response.cookies.get("hollawall_presensi")
        self.assertTrue(session_id)
        payload = response.json()
        self.capture_token = payload["capture_token"]
        return payload, {"Cookie": f"hollawall_presensi={session_id}"}

    def submit(self, origin: str, cookie: dict[str, str], csrf: str, *, action: str, project_id: str = "p26-griya", latitude: float = -7.3546465, longitude: float = 112.7826242, accuracy: float = 10, capture_token: str | None = None, observed_at_ms: int | None = None, origin_header: str | None = None, selfie: bytes | None = None):
        observed_at_ms = observed_at_ms or int(time.time() * 1000)
        response = requests.post(
            origin + "/absen/api/submit.php",
            headers={**cookie, "Origin": origin_header or origin, "Sec-Fetch-Site": "same-origin"},
            data={"csrf": csrf, "capture_token": capture_token or self.capture_token, "employee_id": "pegawai-1", "project_id": project_id, "action": action, "latitude": latitude, "longitude": longitude, "accuracy_m": accuracy, "location_observed_at_ms": observed_at_ms, "selfie_observed_at_ms": observed_at_ms},
            files={"selfie": ("selfie.png", selfie or self.selfie, "image/png")},
            timeout=10,
        )
        if response.status_code == 201:
            self.capture_token = response.json()["capture_token"]
        return response

    def admin_login(self, origin: str) -> dict[str, str]:
        first = requests.get(origin + "/admin/", timeout=5)
        prelogin = first.cookies.get("hollawall_admin")
        self.assertTrue(prelogin)
        response = requests.post(
            origin + "/admin/",
            headers={"Cookie": f"hollawall_admin={prelogin}"},
            data={"username": self.username, "password": self.password, "csrf": self.csrf_from(first.text)},
            allow_redirects=False,
            timeout=5,
        )
        self.assertEqual(response.status_code, 303)
        authenticated = response.cookies.get("hollawall_admin")
        self.assertTrue(authenticated)
        return {"Cookie": f"hollawall_admin={authenticated}"}

    def test_geofence_sequence_private_photo_and_admin_readback(self) -> None:
        with self.server() as origin:
            bootstrap, public_cookie = self.public_bootstrap(origin)
            self.assertEqual([row["name"] for row in bootstrap["employees"]], ["Pegawai 1", "Pegawai 2", "Pegawai 3"])
            self.assertIn("p26-griya", [row["id"] for row in bootstrap["projects"]])
            csrf = bootstrap["csrf"]

            no_checkin = self.submit(origin, public_cookie, csrf, action="check_out")
            self.assertEqual(no_checkin.status_code, 409)
            self.assertEqual(no_checkin.json()["error"]["code"], "check_in_required")

            inaccurate = self.submit(origin, public_cookie, csrf, action="check_in", accuracy=100)
            self.assertEqual(inaccurate.status_code, 422)
            self.assertEqual(inaccurate.json()["error"]["code"], "location_inaccurate")

            outside = self.submit(origin, public_cookie, csrf, action="check_in", latitude=-7.25, longitude=112.70)
            self.assertEqual(outside.status_code, 422)
            self.assertEqual(outside.json()["error"]["code"], "outside_geofence")

            used_capture_token = self.capture_token
            checked_in = self.submit(origin, public_cookie, csrf, action="check_in")
            self.assertEqual(checked_in.status_code, 201, checked_in.text)
            first = checked_in.json()
            self.assertEqual(first["record"]["action"], "check_in")
            csrf = first["csrf"]

            replay = self.submit(origin, public_cookie, csrf, action="check_in", capture_token=used_capture_token)
            self.assertEqual(replay.status_code, 403)
            self.assertEqual(replay.json()["error"]["code"], "capture_expired")

            duplicate = self.submit(origin, public_cookie, csrf, action="check_in")
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(duplicate.json()["error"]["code"], "already_checked_in")

            wrong_project = self.submit(origin, public_cookie, csrf, action="check_out", project_id="p26-fajar")
            self.assertEqual(wrong_project.status_code, 409)
            self.assertEqual(wrong_project.json()["error"]["code"], "project_mismatch")

            checked_out = self.submit(origin, public_cookie, csrf, action="check_out")
            self.assertEqual(checked_out.status_code, 201, checked_out.text)
            second = checked_out.json()
            self.assertEqual(second["record"]["action"], "check_out")
            self.assertEqual(first["record"]["pair_id"], second["record"]["pair_id"])

            unauthenticated = requests.get(origin + "/admin/api/presensi.php?project_id=p26-griya", timeout=5)
            self.assertEqual(unauthenticated.status_code, 401)
            admin_cookie = self.admin_login(origin)
            records_response = requests.get(origin + "/admin/api/presensi.php?project_id=p26-griya", headers=admin_cookie, timeout=5)
            self.assertEqual(records_response.status_code, 200, records_response.text)
            records = records_response.json()["records"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["employee_name"], "Pegawai 1")
            self.assertEqual(records[0]["status"], "completed")
            self.assertIsNotNone(records[0]["check_out"])

            photo_url = records[0]["check_in"]["photo_url"]
            self.assertEqual(requests.get(origin + photo_url, timeout=5).status_code, 401)
            photo = requests.get(origin + photo_url, headers=admin_cookie, timeout=5)
            self.assertEqual(photo.status_code, 200)
            self.assertEqual(photo.headers["Content-Type"], "image/jpeg")
            self.assertTrue(photo.content.startswith(b"\xff\xd8"))
            self.assertTrue(photo.content.endswith(b"\xff\xd9"))
            self.assertNotEqual(photo.content, self.selfie)

            store = self.account_root / ".hollawall-presensi"
            self.assertTrue((store / "events.json").is_file())
            stored = (store / "events.json").read_text(encoding="utf-8")
            self.assertNotIn('"latitude"', stored)
            self.assertNotIn('"longitude"', stored)
            self.assertNotIn('"ip_hash"', stored)
            self.assertTrue((store / "photos").is_dir())
            self.assertFalse((self.web_root / ".hollawall-presensi").exists())
            self.assertEqual((store.stat().st_mode & 0o777), 0o700)
            self.assertTrue(all((path.stat().st_mode & 0o777) == 0o600 for path in (store / "photos").iterdir()))

    def test_rejects_cross_origin_and_stale_observations(self) -> None:
        with self.server() as origin:
            bootstrap, cookie = self.public_bootstrap(origin)
            cross_origin = self.submit(origin, cookie, bootstrap["csrf"], action="check_in", origin_header="https://attacker.invalid")
            self.assertEqual(cross_origin.status_code, 403)
            self.assertEqual(cross_origin.json()["error"]["code"], "origin_invalid")

            stale = self.submit(origin, cookie, bootstrap["csrf"], action="check_in", observed_at_ms=int((time.time() - 180) * 1000))
            self.assertEqual(stale.status_code, 422)
            self.assertEqual(stale.json()["error"]["code"], "location_stale")
            store = self.account_root / ".hollawall-presensi"
            self.assertFalse((store / "events.json").exists())
            self.assertEqual(list((store / "photos").glob("*")), [])

    def test_auto_started_session_cannot_bypass_admin_and_public_session_remains_continuous(self) -> None:
        with self.server(auto_start=True) as origin:
            bootstrap = requests.get(origin + "/absen/api/bootstrap.php", timeout=5)
            self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
            payload = bootstrap.json()
            self.assertTrue(payload["csrf"])
            session_id = bootstrap.cookies.get("hollawall_presensi")
            self.assertTrue(session_id)
            cookie = {"Cookie": f"hollawall_presensi={session_id}"}
            status = requests.get(origin + "/absen/api/status.php?employee_id=pegawai-1", headers=cookie, timeout=5)
            self.assertEqual(status.status_code, 200, status.text)
            submitted = self.submit(
                origin,
                cookie,
                payload["csrf"],
                action="check_in",
                capture_token=payload["capture_token"],
            )
            self.assertEqual(submitted.status_code, 201, submitted.text)
            response = requests.get(origin + "/admin/api/presensi.php?project_id=p26-griya", timeout=5)
            self.assertEqual(response.status_code, 401, response.text)
            self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_haversine_is_finite_for_antipodal_coordinates(self) -> None:
        common = ROOT / "deploy" / "rumahweb-presensi" / "api" / "presensi-common.php"
        script = (
            f"require {str(common)!r}; "
            "$distance=presensi_haversine(55.91330994525936,-25.736136154921923,-55.913309942990246,154.26386383522012); "
            "if (!is_finite($distance)) { exit(9); }"
        )
        result = subprocess.run(["php", "-r", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_black_selfie_without_writing_evidence(self) -> None:
        with self.server() as origin:
            bootstrap, cookie = self.public_bootstrap(origin)
            response = self.submit(origin, cookie, bootstrap["csrf"], action="check_in", selfie=proof_png(solid=(0, 0, 0)))
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["error"]["code"], "selfie_unusable")
            store = self.account_root / ".hollawall-presensi"
            self.assertFalse((store / "events.json").exists())
            self.assertEqual(list((store / "photos").glob("*")), [])

    def test_event_commit_failure_removes_photo_and_temporary_file(self) -> None:
        with self.server(fault="event_rename") as origin:
            bootstrap, cookie = self.public_bootstrap(origin)
            failed = self.submit(origin, cookie, bootstrap["csrf"], action="check_in")
            self.assertEqual(failed.status_code, 503, failed.text)
            self.assertEqual(failed.json()["error"]["code"], "storage_unavailable")
            store = self.account_root / ".hollawall-presensi"
            self.assertFalse((store / "events.json").exists())
            self.assertEqual(list((store / "photos").glob("*")), [])
            self.assertEqual(list(store.glob("events.*.tmp")), [])

    def test_retention_purge_removes_completed_pairs_and_preserves_open_checkins(self) -> None:
        with self.server() as origin:
            bootstrap, cookie = self.public_bootstrap(origin)
            first = self.submit(origin, cookie, bootstrap["csrf"], action="check_in")
            self.assertEqual(first.status_code, 201, first.text)
            second = self.submit(origin, cookie, first.json()["csrf"], action="check_out")
            self.assertEqual(second.status_code, 201, second.text)
            store = self.account_root / ".hollawall-presensi"
            events_path = store / "events.json"
            events = json.loads(events_path.read_text(encoding="utf-8"))
            old_time = "2026-01-01T00:00:00+00:00"
            for event in events:
                event["occurred_at"] = old_time
            open_photo = "evt-ffffffffffffffffffffffff.jpg"
            shutil.copy2(store / "photos" / events[0]["photo_name"], store / "photos" / open_photo)
            (store / "photos" / open_photo).chmod(0o600)
            open_event = {**events[0], "id": "evt-open-proof", "pair_id": "prs-open-proof", "employee_id": "pegawai-2", "employee_name": "Pegawai 2", "photo_name": open_photo}
            events.append(open_event)
            events_path.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")
            events_path.chmod(0o600)
            env = {**os.environ, "HOLLAWALL_PRESENSI_CONFIG": str(self.presensi_config)}
            command = ["php", str(self.web_root / "absen" / "bin" / "purge.php")]
            purged = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
            self.assertIn('"removed_events":2', purged.stdout)
            remaining = json.loads(events_path.read_text(encoding="utf-8"))
            self.assertEqual([event["id"] for event in remaining], ["evt-open-proof"])
            self.assertEqual([path.name for path in (store / "photos").iterdir()], [open_photo])
            rerun = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
            self.assertIn('"removed_events":0', rerun.stdout)

    def test_purge_reconciles_precommit_and_postcommit_quarantines(self) -> None:
        store = self.account_root / ".hollawall-presensi"
        photos = store / "photos"
        photos.mkdir(parents=True, mode=0o700)
        store.chmod(0o700)
        precommit_name = "evt-111111111111111111111111.jpg"
        normal_name = "evt-222222222222222222222222.jpg"
        orphan_name = "evt-333333333333333333333333.jpg"
        events = [
            {"id": "evt-in", "pair_id": "prs-old", "action": "check_in", "occurred_at": "2026-01-01T00:00:00+00:00", "photo_name": precommit_name},
            {"id": "evt-out", "pair_id": "prs-old", "action": "check_out", "occurred_at": "2026-01-01T01:00:00+00:00", "photo_name": normal_name},
        ]
        events_path = store / "events.json"
        events_path.write_text(json.dumps(events) + "\n", encoding="utf-8")
        events_path.chmod(0o600)
        (photos / f"{precommit_name}.purge-aaaaaaaaaaaa").write_bytes(b"precommit")
        (photos / normal_name).write_bytes(b"normal")
        (photos / f"{orphan_name}.purge-bbbbbbbbbbbb").write_bytes(b"postcommit")
        for path in photos.iterdir():
            path.chmod(0o600)
        env = {**os.environ, "HOLLAWALL_PRESENSI_CONFIG": str(self.presensi_config)}
        command = ["php", str(self.web_root / "absen" / "bin" / "purge.php")]
        first = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
        self.assertIn('"removed_events":2', first.stdout)
        self.assertEqual(json.loads(events_path.read_text(encoding="utf-8")), [])
        self.assertEqual(list(photos.iterdir()), [])
        second = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
        self.assertIn('"removed_events":0', second.stdout)
        self.assertEqual(list(photos.iterdir()), [])

    def test_purge_cleanup_failure_is_nonzero(self) -> None:
        store = self.account_root / ".hollawall-presensi"
        photos = store / "photos"
        photos.mkdir(parents=True, mode=0o700)
        store.chmod(0o700)
        (store / "events.json").write_text("[]\n", encoding="utf-8")
        (store / "events.json").chmod(0o600)
        blocked = photos / "evt-444444444444444444444444.jpg.purge-cccccccccccc"
        blocked.mkdir()
        env = {**os.environ, "HOLLAWALL_PRESENSI_CONFIG": str(self.presensi_config)}
        command = ["php", str(self.web_root / "absen" / "bin" / "purge.php")]
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("purge failed", result.stderr.lower())

    def assert_config_rejected(self, config: str) -> None:
        self.presensi_config.write_text(config, encoding="utf-8")
        self.presensi_config.chmod(0o600)
        with self.server() as origin:
            response = requests.get(origin + "/absen/api/bootstrap.php", timeout=5)
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["error"]["code"], "configuration_invalid")

    def test_config_wrong_mode_and_symlink_fail_closed(self) -> None:
        self.presensi_config.chmod(0o644)
        with self.server() as origin:
            wrong_mode = requests.get(origin + "/absen/api/bootstrap.php", timeout=5)
            self.assertEqual(wrong_mode.status_code, 503, wrong_mode.text)
            self.assertEqual(wrong_mode.json()["error"]["code"], "configuration_unavailable")
        self.presensi_config.chmod(0o600)
        real_config = self.account_root / ".hollawall-presensi-real.php"
        self.presensi_config.rename(real_config)
        self.presensi_config.symlink_to(real_config)
        with self.server() as origin:
            symlinked = requests.get(origin + "/absen/api/bootstrap.php", timeout=5)
            self.assertEqual(symlinked.status_code, 503, symlinked.text)
            self.assertEqual(symlinked.json()["error"]["code"], "configuration_insecure")

    def test_all_required_employees_plus_duplicate_fail_closed(self) -> None:
        duplicate = "<?php return ['retention_days'=>90,'employees'=>[['id'=>'pegawai-1','name'=>'Pegawai 1'],['id'=>'pegawai-2','name'=>'Pegawai 2'],['id'=>'pegawai-3','name'=>'Pegawai 3'],['id'=>'pegawai-1','name'=>'Pegawai 1']],'projects'=>[['id'=>'p26-griya','name'=>'Griya Wellness Center','company'=>'Holla','location_label'=>'Lokasi uji','latitude'=>-7.3546465,'longitude'=>112.7826242,'radius_m'=>150,'max_accuracy_m'=>75,'active'=>true]]];"
        self.assert_config_rejected(duplicate)

    def test_active_inactive_duplicate_project_identity_fails_closed(self) -> None:
        duplicate = "<?php return ['retention_days'=>90,'employees'=>[['id'=>'pegawai-1','name'=>'Pegawai 1'],['id'=>'pegawai-2','name'=>'Pegawai 2'],['id'=>'pegawai-3','name'=>'Pegawai 3']],'projects'=>[['id'=>'p26-griya','name'=>'Griya Wellness Center','company'=>'Holla','location_label'=>'Lokasi uji','latitude'=>-7.3546465,'longitude'=>112.7826242,'radius_m'=>150,'max_accuracy_m'=>75,'active'=>true],['id'=>'p26-griya','name'=>'Griya Wellness Center','company'=>'Holla','location_label'=>'Arsip','latitude'=>null,'longitude'=>null,'radius_m'=>null,'max_accuracy_m'=>null,'active'=>false]]];"
        self.assert_config_rejected(duplicate)

    def test_inactive_duplicate_project_names_fail_closed(self) -> None:
        duplicate = "<?php return ['retention_days'=>90,'employees'=>[['id'=>'pegawai-1','name'=>'Pegawai 1'],['id'=>'pegawai-2','name'=>'Pegawai 2'],['id'=>'pegawai-3','name'=>'Pegawai 3']],'projects'=>[['id'=>'p26-griya','name'=>'Griya Wellness Center','company'=>'Holla','location_label'=>'Lokasi uji','latitude'=>-7.3546465,'longitude'=>112.7826242,'radius_m'=>150,'max_accuracy_m'=>75,'active'=>true],['id'=>'p26-old-a','name'=>'Arsip Sama','active'=>false],['id'=>'p26-old-b','name'=>'arsip sama','active'=>false]]];"
        self.assert_config_rejected(duplicate)


if __name__ == "__main__":
    unittest.main()
