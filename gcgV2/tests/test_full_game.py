"""Scripted AI vs AI 完整對局測試 + gamePlay.yaml schema 驗證（不需 LLM）。"""

import random
import unittest

import yaml

from helpers import TestStack


class FullGameTest(unittest.TestCase):
    def test_full_scripted_game(self):
        random.seed(20260612)
        stack = TestStack()
        simulator = stack.build_full_simulator(max_steps=600)
        simulator.start_game(decision_player="P1")
        result = simulator.run()

        self.assertEqual(result["status"], "finished", msg=f"result={result}")
        self.assertIn(result["winner"], {"P1", "P2"})

        with open(result["gameplay_log_path"], "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        # schema：單一 document，必要欄位
        self.assertEqual(payload["schema_version"], "2.0")
        self.assertEqual(payload["game_id"], result["game_id"])
        self.assertEqual(payload["summary"]["status"], "finished")
        self.assertEqual(payload["summary"]["winner"], result["winner"])
        events = payload["events"]
        self.assertGreater(len(events), 10)

        # seq 單調遞增
        seqs = [event["seq"] for event in events]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), len(set(seqs)))

        # gamePlay.yaml 是 review/debug log：包含雙方手牌明細，但不得洩漏牌庫順序
        for event in events:
            features = event.get("features") or {}
            for side in ("p1", "p2"):
                block = features.get(side) or {}
                self.assertIn("hand", block)
                self.assertIsInstance(block["hand"], list)
                self.assertEqual(len(block["hand"]), block["hand_count"])
                self.assertNotIn("deck", block)
                self.assertIn("hand_count", block)

        # 對局結束狀態一致
        self.assertTrue(stack.runtime.is_game_over())
        self.assertEqual(stack.runtime.get_winner(), result["winner"])

    def test_opening_flow_creates_choices_in_order(self):
        random.seed(7)
        stack = TestStack()
        simulator = stack.build_full_simulator(max_steps=600)
        simulator.start_game(decision_player="P2")
        # 開局第一個 pending choice 是 P2 的先後攻選擇
        pending = stack.state.peek_pending_choice()
        self.assertEqual(pending["type"], "choose_turn_order")
        self.assertEqual(pending["player_id"], "P2")
        result = simulator.run()
        self.assertEqual(result["status"], "finished")
        # 開局設置正確：雙方 6 盾、後手 1 EX（遊戲中 EX 可能已被消耗，改驗 log）
        with open(result["gameplay_log_path"], "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
        setup_events = [
            event for event in payload["events"]
            if "開局設置完成" in (event.get("message") or "")
        ]
        self.assertEqual(len(setup_events), 1)
        features = setup_events[0]["features"]
        first_player = features["opening"]["first_player"]
        second = "P2" if first_player == "P1" else "P1"
        self.assertEqual(features[second.lower()]["resources"]["ex"], 1)
        self.assertEqual(features["p1"]["shields"], 6)
        self.assertEqual(features["p2"]["shields"], 6)


if __name__ == "__main__":
    unittest.main()
