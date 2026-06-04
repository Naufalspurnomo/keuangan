import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from services import state_manager as state


class StateManagerSafetyTests(unittest.TestCase):
    def test_validate_state_payload_skips_invalid_sections(self):
        payload = {
            "pending_transactions": {"user": {"created_at": datetime.now().isoformat()}},
            "processed_messages": [],
            "last_bot_reports": {"chat": "msg"},
        }

        validated = state._validate_state_payload(payload, "unit-test")

        self.assertIn("pending_transactions", validated)
        self.assertIn("last_bot_reports", validated)
        self.assertNotIn("processed_messages", validated)

    def test_atomic_write_keeps_previous_file_as_backup(self):
        with tempfile.TemporaryDirectory(dir=".") as temp_dir:
            path = os.path.join(temp_dir, "state.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"version": 1}')

            state._write_state_file_atomic(path, '{"version": 2}')

            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
            with open(f"{path}.bak", "r", encoding="utf-8") as f:
                backup = json.load(f)

            self.assertEqual(current, {"version": 2})
            self.assertEqual(backup, {"version": 1})

    def test_pending_confirmation_expiry_removes_entry_without_deadlock(self):
        key = "chat:user"
        state.PENDING_CONFIRMATIONS[key] = {
            "type": "unit",
            "timestamp": datetime.now() - timedelta(minutes=30),
            "expires_at": datetime.now() - timedelta(seconds=1),
        }

        with patch.object(state, "_save_state", lambda: None):
            self.assertIsNone(state.get_pending_confirmation("user", "chat"))

        self.assertNotIn(key, state.PENDING_CONFIRMATIONS)

    def test_dedup_upgrade_path_runs_save_outside_lock(self):
        with patch.object(state, "_save_state", lambda: None):
            self.assertFalse(state.is_message_duplicate("unit-dedup", score=1))
            self.assertTrue(state.is_message_duplicate("unit-dedup", score=1))
            self.assertFalse(state.is_message_duplicate("unit-dedup", score=10, allow_upgrade=True))

    def test_external_state_payload_excludes_visual_buffer(self):
        payload = {
            "pending_transactions": {"p1": {"transactions": []}},
            "visual_buffer": {"chat:user": [{"media_url": "data:image/jpeg;base64,abc"}]},
        }

        external = state._external_state_payload(payload)

        self.assertIn("pending_transactions", external)
        self.assertNotIn("visual_buffer", external)

    def test_external_store_required_fails_closed_when_missing(self):
        with patch.object(state, "get_configured_state_store", lambda: None), \
             patch.object(state, "external_state_required", lambda: True):
            with self.assertRaises(RuntimeError):
                state._load_state_from_external()

    def test_save_state_required_external_failure_is_not_swallowed(self):
        with patch.object(state, "get_configured_state_store", lambda: None), \
             patch.object(state, "external_state_required", lambda: True), \
             patch.object(state, "_write_state_file_atomic", lambda path, contents: None):
            with self.assertRaises(RuntimeError):
                state._save_state()

    def test_external_store_load_validates_payload(self):
        class FakeStore:
            def load(self):
                return {
                    "pending_transactions": {"p1": {"transactions": []}},
                    "processed_messages": [],
                }

        with patch.object(state, "get_configured_state_store", lambda: FakeStore()):
            loaded = state._load_state_from_external()

        self.assertIn("pending_transactions", loaded)
        self.assertNotIn("processed_messages", loaded)

    def test_project_knowledge_resolves_alias_in_scope(self):
        old_knowledge = {
            "projects": dict(state._project_knowledge.get("projects", {})),
            "aliases": dict(state._project_knowledge.get("aliases", {})),
        }
        old_registry = dict(state._project_registry)
        try:
            state._project_knowledge["projects"] = {}
            state._project_knowledge["aliases"] = {}
            state._project_registry.clear()
            with patch.object(state, "_save_state", lambda: None):
                state.remember_project_knowledge(
                    "HOJJA - Taman Beringas Selatan",
                    "CV HB(101)",
                    company="HOJJA",
                    aliases=["beringas"],
                )

            result = state.resolve_project_knowledge(
                "beringas",
                dompet_sheet="CV HB(101)",
                company="HOJJA",
            )

            self.assertEqual(result["status"], "EXACT")
            self.assertEqual(result["final_name"], "HOJJA - Taman Beringas Selatan")
            self.assertEqual(result["dompet"], "CV HB(101)")
            self.assertEqual(result["company"], "HOJJA")
        finally:
            state._project_knowledge["projects"] = old_knowledge["projects"]
            state._project_knowledge["aliases"] = old_knowledge["aliases"]
            state._project_registry.clear()
            state._project_registry.update(old_registry)

    def test_project_knowledge_keeps_duplicate_alias_ambiguous(self):
        old_knowledge = {
            "projects": dict(state._project_knowledge.get("projects", {})),
            "aliases": dict(state._project_knowledge.get("aliases", {})),
        }
        old_registry = dict(state._project_registry)
        try:
            state._project_knowledge["projects"] = {}
            state._project_knowledge["aliases"] = {}
            state._project_registry.clear()
            with patch.object(state, "_save_state", lambda: None):
                state.remember_project_knowledge(
                    "HOJJA - Taman Beringas Selatan",
                    "CV HB(101)",
                    company="HOJJA",
                    aliases=["beringas"],
                )
                state.remember_project_knowledge(
                    "HOLLA - Beringas Festival",
                    "CV HB(101)",
                    company="HOLLA",
                    aliases=["beringas"],
                )

            result = state.resolve_project_knowledge("beringas", dompet_sheet="CV HB(101)")

            self.assertEqual(result["status"], "AMBIGUOUS")
            self.assertEqual(result["match_count"], 2)
        finally:
            state._project_knowledge["projects"] = old_knowledge["projects"]
            state._project_knowledge["aliases"] = old_knowledge["aliases"]
            state._project_registry.clear()
            state._project_registry.update(old_registry)

    def test_cloud_save_scheduler_drains_payload(self):
        calls = []
        done = threading.Event()

        def fake_save(payload):
            calls.append(payload)
            done.set()

        with state._cloud_save_lock:
            state._cloud_save_latest = None
            state._cloud_save_thread_running = False

        with patch.object(state, "save_state_to_cloud", fake_save):
            state._schedule_cloud_state_save('{"ok": true}')
            self.assertTrue(done.wait(2))

        for _ in range(20):
            with state._cloud_save_lock:
                running = state._cloud_save_thread_running
            if not running:
                break
            time.sleep(0.01)

        self.assertEqual(calls, ['{"ok": true}'])
        with state._cloud_save_lock:
            self.assertFalse(state._cloud_save_thread_running)


if __name__ == "__main__":
    unittest.main()
