from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BATTLE_APP_ROOT = Path(__file__).resolve().parents[1]
GCGV2_ROOT = BATTLE_APP_ROOT.parent
if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))
if str(BATTLE_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(BATTLE_APP_ROOT))

from battle_app.runtime_document import (  # noqa: E402
    DocumentBackedBattle,
    MongoBattleService,
    card_detail,
)
from battle_app.storage import AI_LOCK_TTL, MongoGameStore, utc_now  # noqa: E402
from battle_app.tests.test_mongo_storage import FakeClient  # noqa: E402


class RuntimeDocumentTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix="gcg_doc_runtime_")
        self.old_env = {
            "GCG_V2_OUTPUT_ROOT": os.environ.get("GCG_V2_OUTPUT_ROOT"),
            "GCG_BATTLE_APP_TMP_OUTPUT_ROOT": os.environ.get("GCG_BATTLE_APP_TMP_OUTPUT_ROOT"),
            "GCG_BATTLE_AI_MODE": os.environ.get("GCG_BATTLE_AI_MODE"),
            "GCG_BATTLE_INTERPRETER": os.environ.get("GCG_BATTLE_INTERPRETER"),
        }
        os.environ["GCG_V2_OUTPUT_ROOT"] = self.tmpdir.name
        os.environ["GCG_BATTLE_APP_TMP_OUTPUT_ROOT"] = self.tmpdir.name
        os.environ["GCG_BATTLE_AI_MODE"] = "scripted"
        os.environ["GCG_BATTLE_INTERPRETER"] = "reference"
        self.store = MongoGameStore(client=FakeClient())
        self.service = MongoBattleService(self.store)

    def tearDown(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmpdir.cleanup()

    def test_state_read_uses_stored_document_without_hydrating_runner(self):
        created = self.service.create_game()
        game_id = created["game_id"]

        with patch.object(DocumentBackedBattle, "hydrate", side_effect=AssertionError("should not hydrate")):
            state = self.service.get_state(game_id)

        self.assertEqual(state["game_id"], game_id)
        self.assertEqual(state["status"], "waiting_human")
        self.assertTrue(state["legal_actions"])
        self.assertEqual(state["message"], "請選擇先攻或後攻")

    def test_command_hydrates_updates_state_and_preserves_public_events(self):
        created = self.service.create_game()
        game_id = created["game_id"]
        before = self.store.get_game(game_id)

        response = self.service.submit_command(game_id, "choose go_first")
        after = self.store.get_game(game_id)

        self.assertEqual(response["game_id"], game_id)
        self.assertEqual(response["status"], "waiting_human")
        self.assertGreater(after["version"], before["version"])
        self.assertEqual(after["runtime_state"]["game_id"], game_id)
        self.assertEqual(after["status"], "waiting_human")
        self.assertTrue(after["legal_commands"])
        self.assertTrue(response["events"])

    def test_card_detail_uses_cached_card_database_without_game_session(self):
        detail = card_detail("st01/ST01-008")

        self.assertEqual(detail["id"], "ST01-008")
        self.assertTrue(detail["name"])
        self.assertIn("descriptions", detail)

    def test_waiting_ai_only_pass_auto_passes_without_calling_player(self):
        resolved = []

        def fail_decide(*_args, **_kwargs):
            raise AssertionError("AI player should not be called for pass-only window")

        runner = SimpleNamespace(
            runtime=SimpleNamespace(resolve_command=lambda parsed: resolved.append(parsed.command_line())),
            players={"P2": SimpleNamespace(decide=fail_decide)},
        )
        battle = DocumentBackedBattle(runner=runner, status="waiting_ai")
        battle._advance_and_update_status = lambda: None
        battle._current_decision = lambda: ("P2", ["pass"], None)
        battle.response = lambda: {"status": battle.status, "message": battle.last_message}

        response, latency = battle.run_ai_once()

        self.assertEqual(resolved, ["pass"])
        self.assertEqual(latency, 0.0)
        self.assertEqual(response["message"], "P2 沒有可用操作，自動讓過。")

    def test_waiting_ai_state_uses_lock_so_concurrent_polls_run_one_ai_step(self):
        created = self.service.create_game()
        game_id = created["game_id"]
        self.service.submit_command(game_id, "choose go_first")
        waiting = self.service.submit_command(game_id, "choose keep")
        self.assertEqual(waiting["status"], "waiting_ai")

        original = DocumentBackedBattle.run_ai_once
        calls = []
        calls_lock = threading.Lock()

        def counted_run_ai_once(instance):
            with calls_lock:
                calls.append(time.time())
            time.sleep(0.15)
            return original(instance)

        results = []

        def poll_state():
            results.append(self.service.get_state(game_id))

        with patch.object(DocumentBackedBattle, "run_ai_once", new=counted_run_ai_once):
            threads = [threading.Thread(target=poll_state) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(len(calls), 1)
        stored = self.store.get_game(game_id)
        self.assertIsNone(stored["ai_lock_until"])
        self.assertIsNone(stored["ai_lock_owner"])
        self.assertIn("last_ai_latency_seconds", stored)
        self.assertIn("last_ai_lock_owner", stored)
        self.assertGreaterEqual(stored["last_ai_latency_seconds"], 0)
        self.assertTrue(stored["last_ai_lock_owner"].startswith("poll-"))

    def test_ai_lock_expires_after_ninety_seconds(self):
        created = self.service.create_game()
        game_id = created["game_id"]
        self.service.submit_command(game_id, "choose go_first")
        self.service.submit_command(game_id, "choose keep")

        now = utc_now()
        first_lock = self.store.acquire_ai_lock(game_id, owner="first", now=now)
        self.assertIsNotNone(first_lock)
        second_lock = self.store.acquire_ai_lock(game_id, owner="second", now=now + timedelta(seconds=30))
        self.assertIsNone(second_lock)
        expired_lock = self.store.acquire_ai_lock(
            game_id,
            owner="after-expiry",
            now=now + AI_LOCK_TTL + timedelta(seconds=1),
        )
        self.assertIsNotNone(expired_lock)
        self.assertEqual(expired_lock["ai_lock_owner"], "after-expiry")


if __name__ == "__main__":
    unittest.main()
