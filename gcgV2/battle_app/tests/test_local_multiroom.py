from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BATTLE_APP_ROOT = Path(__file__).resolve().parents[1]
GCGV2_ROOT = BATTLE_APP_ROOT.parent
if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))
if str(BATTLE_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(BATTLE_APP_ROOT))

from battle_app.server import BattleAppHandler, BattleGameRegistry, PUBLIC_ROOT  # noqa: E402
from reviewboard.humanVsAI.battle_session import AI_PLAYER  # noqa: E402


class SlowScriptedPlayer:
    def __init__(self, command="choose keep", delay=0.35):
        self.command = command
        self.delay = delay

    def decide(self, game_id, player_id, prompt_payload):
        time.sleep(self.delay)
        return f"CONSIDER: 測試慢速 AI。\nCOMMAND: {self.command}"


class QuietBattleAppHandler(BattleAppHandler):
    registry = BattleGameRegistry()

    def log_message(self, _format, *args):
        pass


class LocalMultiRoomTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix="gcg_battle_app_test_")
        self.old_env = {
            "GCG_V2_OUTPUT_ROOT": os.environ.get("GCG_V2_OUTPUT_ROOT"),
            "GCG_BATTLE_AI_MODE": os.environ.get("GCG_BATTLE_AI_MODE"),
            "GCG_BATTLE_INTERPRETER": os.environ.get("GCG_BATTLE_INTERPRETER"),
            "GCG_ENABLE_SCENARIO_MODE": os.environ.get("GCG_ENABLE_SCENARIO_MODE"),
            "GCG_ENABLE_MANUAL_MODE": os.environ.get("GCG_ENABLE_MANUAL_MODE"),
        }
        os.environ["GCG_V2_OUTPUT_ROOT"] = self.tmpdir.name
        os.environ["GCG_BATTLE_AI_MODE"] = "scripted"
        os.environ["GCG_BATTLE_INTERPRETER"] = "reference"
        os.environ["GCG_ENABLE_SCENARIO_MODE"] = "1"
        os.environ["GCG_ENABLE_MANUAL_MODE"] = "1"

        QuietBattleAppHandler.registry = BattleGameRegistry()
        handler = partial(QuietBattleAppHandler, directory=str(PUBLIC_ROOT))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmpdir.cleanup()

    def request(self, path, method="GET", payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def start_game(self):
        status, payload = self.request("/api/games", method="POST", payload={})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        return payload

    def submit_first_action(self, game_id, payload):
        command = payload["legal_actions"][0]["command"]
        return self.request(
            f"/api/games/{game_id}/command",
            method="POST",
            payload={"command": command},
        )

    def test_two_games_are_isolated_and_delete_only_removes_target(self):
        game_a = self.start_game()
        game_b = self.start_game()
        game_a_id = game_a["game_id"]
        game_b_id = game_b["game_id"]
        self.assertNotEqual(game_a_id, game_b_id)

        status, before_b = self.request(f"/api/games/{game_b_id}/state")
        self.assertEqual(status, 200)
        status, after_a_command = self.submit_first_action(game_a_id, game_a)
        self.assertEqual(status, 200)
        self.assertTrue(after_a_command["ok"])
        status, after_b = self.request(f"/api/games/{game_b_id}/state")
        self.assertEqual(status, 200)
        self.assertEqual(before_b["viewer_state"], after_b["viewer_state"])

        status, missing = self.request("/api/games/not_a_game/state")
        self.assertEqual(status, 404)
        self.assertFalse(missing["ok"])

        status, deleted = self.request(f"/api/games/{game_a_id}", method="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        status, deleted_state = self.request(f"/api/games/{game_a_id}/state")
        self.assertEqual(status, 404)
        self.assertFalse(deleted_state["ok"])
        status, still_b = self.request(f"/api/games/{game_b_id}/state")
        self.assertEqual(status, 200)
        self.assertEqual(still_b["game_id"], game_b_id)

    def test_waiting_ai_polling_does_not_block(self):
        game = self.start_game()
        game_id = game["game_id"]
        status, after_order = self.request(
            f"/api/games/{game_id}/command",
            method="POST",
            payload={"command": "choose go_first"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(after_order["status"], "waiting_human")

        record = QuietBattleAppHandler.registry.get(game_id)
        self.assertIsNotNone(record)
        record.session._runner.players[AI_PLAYER] = SlowScriptedPlayer()

        status, waiting = self.request(
            f"/api/games/{game_id}/command",
            method="POST",
            payload={"command": "choose keep"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(waiting["status"], "waiting_ai")

        latencies = []
        for _ in range(3):
            started = time.time()
            status, payload = self.request(f"/api/games/{game_id}/state")
            latencies.append(time.time() - started)
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "waiting_ai")
            time.sleep(0.02)
        self.assertTrue(all(latency < 0.1 for latency in latencies), latencies)

        deadline = time.time() + 2
        final = waiting
        while time.time() < deadline:
            _status, final = self.request(f"/api/games/{game_id}/state")
            if final["status"] != "waiting_ai":
                break
            time.sleep(0.05)
        self.assertEqual(final["status"], "waiting_human")

    def test_can_start_manual_scenario_game(self):
        status, payload = self.request(
            "/api/games/scenario",
            method="POST",
            payload={"scenario_id": "st01-008-playable"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "waiting_human")
        self.assertIn("st01/ST01-008", payload["viewer_state"]["players"]["P1"]["hand"])
        self.assertIn("play_card st01/ST01-008 0", payload["legal_commands"])
        self.assertEqual(payload["viewer_state"]["players"]["P2"]["hand"], [])
        self.assertEqual(payload["events"][-1]["event_type"], "scenario_loaded")

    def test_command_scenario_exposes_command_card(self):
        status, payload = self.request(
            "/api/games/scenario",
            method="POST",
            payload={"scenario_id": "st01-012-rested-target"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("play_card st01/ST01-012", payload["legal_commands"])

        status, after_command = self.request(
            f"/api/games/{payload['game_id']}/command",
            method="POST",
            payload={"command": "play_card st01/ST01-012"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(after_command["ok"])
        self.assertEqual(after_command["decision_type"], "pending_choice")
        self.assertEqual(after_command["legal_commands"], ["choose opponent_slot_0"])

    def test_scenario_route_requires_feature_flag(self):
        os.environ["GCG_ENABLE_SCENARIO_MODE"] = "0"

        status, payload = self.request(
            "/api/games/scenario",
            method="POST",
            payload={"scenario_id": "st01-008-playable"},
        )

        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_manual_scenario_switches_viewer_to_p2(self):
        status, payload = self.request(
            "/api/games/scenario",
            method="POST",
            payload={"scenario_id": "st01-008-playable", "mode": "manual"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["viewer_state"]["viewer_player"], "P1")
        self.assertIn("pass", payload["legal_commands"])

        status, after_pass = self.request(
            f"/api/games/{payload['game_id']}/command",
            method="POST",
            payload={"command": "pass"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(after_pass["ok"])
        self.assertEqual(after_pass["status"], "waiting_human")
        self.assertEqual(after_pass["viewer_state"]["viewer_player"], "P2")
        self.assertEqual(after_pass["viewer_state"]["opponent_player"], "P1")
        self.assertEqual(after_pass["viewer_state"]["players"]["P1"]["hand"], [])
        self.assertIn("pass", after_pass["legal_commands"])

    def test_can_start_fresh_manual_game(self):
        status, payload = self.request(
            "/api/games",
            method="POST",
            payload={"mode": "manual"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "waiting_human")
        self.assertEqual(payload["viewer_state"]["viewer_player"], "P1")
        self.assertIn("choose go_first", payload["legal_commands"])

        status, after_order = self.request(
            f"/api/games/{payload['game_id']}/command",
            method="POST",
            payload={"command": "choose go_first"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(after_order["viewer_state"]["viewer_player"], "P1")
        self.assertIn("choose keep", after_order["legal_commands"])

        status, after_keep = self.request(
            f"/api/games/{payload['game_id']}/command",
            method="POST",
            payload={"command": "choose keep"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(after_keep["ok"])
        self.assertEqual(after_keep["status"], "waiting_human")
        self.assertEqual(after_keep["viewer_state"]["viewer_player"], "P2")
        self.assertIn("choose keep", after_keep["legal_commands"])

    def test_manual_mode_requires_feature_flag(self):
        os.environ["GCG_ENABLE_MANUAL_MODE"] = "0"

        status, payload = self.request(
            "/api/games/scenario",
            method="POST",
            payload={"scenario_id": "st01-008-playable", "mode": "manual"},
        )

        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_public_event_does_not_reveal_hidden_shield_card_name(self):
        status, payload = self.request(
            "/api/games/scenario",
            method="POST",
            payload={"scenario_id": "st01-008-playable"},
        )
        self.assertEqual(status, 200)
        record = QuietBattleAppHandler.registry.get(payload["game_id"])

        message = record.session._public_message({
            "actor": "system",
            "event_type": "rule_event",
            "message": "P1 breaks a hidden defense card (st01/ST01-009).",
            "result": {"payload": {"hidden_card_ids": ["st01/ST01-009"]}},
        })

        self.assertEqual(message, "P1 breaks a hidden defense card (卡牌).")

        public_message = record.session._public_message({
            "actor": "system",
            "event_type": "rule_event",
            "message": "P1 使用 st01/ST01-008。",
            "result": {"payload": {"hidden_card_ids": ["st01/ST01-009"]}},
        })

        self.assertIn("Demi Trainer", public_message)

    def test_real_shield_break_events_do_not_reveal_hidden_card_name(self):
        status, payload = self.request(
            "/api/games/scenario",
            method="POST",
            payload={"scenario_id": "st01-shield-break-redaction", "mode": "manual"},
        )
        self.assertEqual(status, 200)
        self.assertIn("attack my_slot_0 opponent_base", payload["legal_commands"])

        status, after_attack = self.request(
            f"/api/games/{payload['game_id']}/command",
            method="POST",
            payload={"command": "attack my_slot_0 opponent_base"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(after_attack["viewer_state"]["viewer_player"], "P2")
        self.assertIn("pass", after_attack["legal_commands"])

        status, after_defender_pass = self.request(
            f"/api/games/{payload['game_id']}/command",
            method="POST",
            payload={"command": "pass"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(after_defender_pass["viewer_state"]["viewer_player"], "P1")
        self.assertIn("pass", after_defender_pass["legal_commands"])

        status, after_damage = self.request(
            f"/api/games/{payload['game_id']}/command",
            method="POST",
            payload={"command": "pass"},
        )
        self.assertEqual(status, 200)

        messages = "\n".join(event["message"] for event in after_damage["events"])
        self.assertIn("P1 擊破 P2 1 面盾牌（卡牌）。", messages)
        self.assertIn("P2 的盾牌 卡牌 被破壞並進入廢棄區。", messages)
        self.assertNotIn("st01/ST01-009", messages)
        self.assertNotIn("Zowort", messages)


if __name__ == "__main__":
    unittest.main()
