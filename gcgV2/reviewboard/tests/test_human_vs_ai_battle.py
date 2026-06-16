from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen


REVIEWBOARD_ROOT = Path(__file__).resolve().parents[1]
if str(REVIEWBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(REVIEWBOARD_ROOT))

from humanVsAI.battle_session import AI_PLAYER, HumanVsAiBattleSession  # noqa: E402
from server import ReviewBoardHandler, env_flag_enabled  # noqa: E402


class SlowScriptedPlayer:
    def __init__(self, command="choose keep", delay=0.35):
        self.command = command
        self.delay = delay

    def decide(self, game_id, player_id, prompt_payload):
        time.sleep(self.delay)
        return f"CONSIDER: 測試慢速 AI。\nCOMMAND: {self.command}"


class CountingPlayer:
    def __init__(self):
        self.calls = 0

    def decide(self, game_id, player_id, prompt_payload):
        self.calls += 1
        return "CONSIDER: should not be called.\nCOMMAND: pass"


class DummyBattleSession:
    def __init__(self, name):
        self.name = name
        self.commands = []

    def state(self):
        return {"ok": True, "route": self.name, "action": "state"}

    def start(self):
        return {"ok": True, "route": self.name, "action": "start"}

    def reset(self):
        return {"ok": True, "route": self.name, "action": "reset"}

    def submit_command(self, command):
        self.commands.append(command)
        return {"ok": True, "route": self.name, "action": "command", "command": command}


class QuietReviewBoardHandler(ReviewBoardHandler):
    def log_message(self, _format, *args):
        pass


class HumanVsAiBattleTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix="gcg_battle_test_")
        self.old_output_root = os.environ.get("GCG_V2_OUTPUT_ROOT")
        os.environ["GCG_V2_OUTPUT_ROOT"] = self.tmpdir.name

    def tearDown(self):
        if self.old_output_root is None:
            os.environ.pop("GCG_V2_OUTPUT_ROOT", None)
        else:
            os.environ["GCG_V2_OUTPUT_ROOT"] = self.old_output_root
        self.tmpdir.cleanup()

    def new_session(self):
        return HumanVsAiBattleSession(players_mode="scripted", interpreter_mode="reference")

    def force_p2_pass_only_decision(self, session):
        raw_state = session._runner.state.get_state()
        raw_state["pending_choice"] = []
        raw_state["trigger_queue"] = []
        raw_state["phase"] = "main"
        raw_state["step"] = None
        raw_state["turn"] = 1
        raw_state["active_player"] = AI_PLAYER
        raw_state["priority_player"] = AI_PLAYER
        raw_state["players"][AI_PLAYER]["hand"] = []
        raw_state["players"][AI_PLAYER]["battle_area"] = [
            {
                "slot": index,
                "unit_id": None,
                "pilot_id": None,
                "pilot_name": None,
                "base_ap": 0,
                "base_hp": 0,
                "pilot_ap": 0,
                "pilot_hp": 0,
                "temp_ap_mod": 0,
                "cont_ap_mod": 0,
                "ap": 0,
                "hp": 0,
                "damage": 0,
                "status": None,
                "keywords": [],
                "link_names": [],
                "is_link": False,
                "is_token": False,
                "turns_on_field": 0,
            }
            for index in range(6)
        ]
        session._runner.state.clear_action_window()
        session._status = "waiting_ai"

    def test_start_returns_safe_p1_state(self):
        payload = self.new_session().start()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "waiting_human")
        self.assertEqual(payload["viewer_state"]["viewer_player"], "P1")
        self.assertEqual(payload["viewer_state"]["players"]["P2"]["hand"], [])
        self.assertIn("選擇先攻", [action["label"] for action in payload["legal_actions"]])
        self.assertNotIn('"deck":', json.dumps(payload, ensure_ascii=False))
        self.assertNotIn('"shield":', json.dumps(payload, ensure_ascii=False))

    def test_rejects_illegal_human_command(self):
        session = self.new_session()
        session.start()
        payload = session.submit_command("play_card st01/ST01-999 0")

        self.assertFalse(payload["ok"])
        self.assertIn("指令執行失敗", payload["error"])

    def test_waiting_ai_polling_does_not_block(self):
        session = self.new_session()
        session.start()
        session.submit_command("choose go_first")
        session._runner.players[AI_PLAYER] = SlowScriptedPlayer()

        waiting = session.submit_command("choose keep")
        self.assertEqual(waiting["status"], "waiting_ai")

        latencies = []
        for _ in range(3):
            start = time.time()
            state = session.state()
            latencies.append(time.time() - start)
            self.assertEqual(state["status"], "waiting_ai")
            time.sleep(0.02)

        self.assertTrue(all(latency < 0.1 for latency in latencies), latencies)

        deadline = time.time() + 2
        final = session.state()
        while time.time() < deadline:
            final = session.state()
            if final["status"] != "waiting_ai":
                break
            time.sleep(0.05)

        self.assertEqual(final["status"], "waiting_human")

    def test_public_events_redact_card_ids(self):
        session = self.new_session()
        session.start()
        session.submit_command("choose go_first")
        session.submit_command("choose keep")

        deadline = time.time() + 2
        payload = session.state()
        while time.time() < deadline:
            payload = session.state()
            if payload["status"] != "waiting_ai":
                break
            time.sleep(0.05)

        events_blob = json.dumps(payload["events"], ensure_ascii=False)
        self.assertNotIn("st01/", events_blob)
        self.assertNotIn('"deck":', json.dumps(payload, ensure_ascii=False))
        self.assertNotIn('"shield":', json.dumps(payload, ensure_ascii=False))

    def test_auto_pass_ai_no_move_skips_ai_decide(self):
        session = HumanVsAiBattleSession(
            players_mode="hermes",
            interpreter_mode="reference",
            auto_pass_ai_no_move=True,
        )
        session.start()
        player = CountingPlayer()
        session._runner.players[AI_PLAYER] = player

        self.force_p2_pass_only_decision(session)

        task = session._build_ai_task_locked(session._generation)

        self.assertIsNone(task)
        self.assertEqual(player.calls, 0)
        self.assertEqual(session._status, "waiting_human")
        self.assertEqual(session._last_message, "P2 沒有可用操作，自動讓過。")
        events = session._public_events_locked()
        self.assertIn("P2 自動讓過（沒有可用操作）。", [event["message"] for event in events])

    def test_auto_pass_ai_no_move_does_not_skip_non_hermes_player(self):
        session = HumanVsAiBattleSession(
            players_mode="scripted",
            interpreter_mode="reference",
            auto_pass_ai_no_move=True,
        )
        session.start()
        self.force_p2_pass_only_decision(session)

        task = session._build_ai_task_locked(session._generation)

        self.assertIsNotNone(task)
        self.assertEqual(session._status, "waiting_ai")
        self.assertEqual(task[4], ["pass"])

    def test_server_routes_battle_v2_to_separate_session(self):
        v1_session = DummyBattleSession("v1")
        v2_session = DummyBattleSession("v2")
        QuietReviewBoardHandler.battle_session = v1_session
        QuietReviewBoardHandler.battle_v2_session = v2_session

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietReviewBoardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            v1_state = json.loads(urlopen(f"{base_url}/api/battle/state", timeout=2).read())
            v2_state = json.loads(urlopen(f"{base_url}/api/battleV2/state", timeout=2).read())
            request = Request(
                f"{base_url}/api/battleV2/command",
                data=json.dumps({"command": "pass"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            v2_command = json.loads(urlopen(request, timeout=2).read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(v1_state["route"], "v1")
        self.assertEqual(v2_state["route"], "v2")
        self.assertEqual(v2_command["route"], "v2")
        self.assertEqual(v2_session.commands, ["pass"])
        self.assertEqual(v1_session.commands, [])

    def test_env_flag_enabled(self):
        old_value = os.environ.get("GCG_BATTLE_AI_AUTO_PASS_NO_MOVE")
        try:
            os.environ["GCG_BATTLE_AI_AUTO_PASS_NO_MOVE"] = "1"
            self.assertTrue(env_flag_enabled("GCG_BATTLE_AI_AUTO_PASS_NO_MOVE"))
            os.environ["GCG_BATTLE_AI_AUTO_PASS_NO_MOVE"] = "false"
            self.assertFalse(env_flag_enabled("GCG_BATTLE_AI_AUTO_PASS_NO_MOVE"))
        finally:
            if old_value is None:
                os.environ.pop("GCG_BATTLE_AI_AUTO_PASS_NO_MOVE", None)
            else:
                os.environ["GCG_BATTLE_AI_AUTO_PASS_NO_MOVE"] = old_value


if __name__ == "__main__":
    unittest.main()
