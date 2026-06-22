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
        }
        os.environ["GCG_V2_OUTPUT_ROOT"] = self.tmpdir.name
        os.environ["GCG_BATTLE_AI_MODE"] = "scripted"
        os.environ["GCG_BATTLE_INTERPRETER"] = "reference"

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


if __name__ == "__main__":
    unittest.main()
