"""Effect / trigger / resolve loop 整合測試（reference interpreter，不需 LLM）。"""

import unittest

from helpers import TestStack


class EffectFlowTest(unittest.TestCase):
    def setUp(self):
        self.stack = TestStack()

    # ------------------------------------------------------------------
    # [Deploy] 觸發 → effect_target pending choice → rest
    # ------------------------------------------------------------------

    def test_deploy_trigger_rest_enemy(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.set_hand("P1", ["st01/ST01-004"])
        stack.put_unit("P2", "st01/ST01-005", 0, status="active")  # 2/2 → 合法目標

        parsed = stack.parse("play_card st01/ST01-004 0", "P1")
        stack.runtime.resolve_command(parsed)

        pending = stack.state.peek_pending_choice()
        self.assertIsNotNone(pending)
        self.assertEqual(pending["type"], "effect_target")
        self.assertEqual(pending["player_id"], "P1")
        option_ids = [option["id"] for option in pending["options"]]
        self.assertIn("opponent_slot_0", option_ids)

        choose = stack.parse("choose opponent_slot_0", "P1")
        stack.runtime.resolve_pending_choice(choose, pending)
        self.assertEqual(stack.state.get_slot("P2", 0)["status"], "rested")

    def test_deploy_trigger_no_target_fizzles(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.set_hand("P1", ["st01/ST01-004"])
        stack.put_unit("P2", "st01/ST01-001", 0, status="active")  # 4HP > 2 → 無合法目標

        parsed = stack.parse("play_card st01/ST01-004 0", "P1")
        stack.runtime.resolve_command(parsed)
        self.assertIsNone(stack.state.peek_pending_choice())

    # ------------------------------------------------------------------
    # Command 卡：MAIN 傷害 rested 敵人 + 致死進廢棄區
    # ------------------------------------------------------------------

    def test_command_card_damage_rested_enemy(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.set_hand("P1", ["st01/ST01-012"])
        target = stack.put_unit("P2", "st01/ST01-008", 0, status="rested")  # 1/1
        target["damage"] = 0

        parsed = stack.parse("play_card st01/ST01-012", "P1")
        stack.runtime.resolve_command(parsed)
        pending = stack.state.peek_pending_choice()
        self.assertEqual(pending["type"], "effect_target")
        stack.runtime.resolve_pending_choice(stack.parse("choose opponent_slot_0", "P1"), pending)

        self.assertIsNone(stack.state.get_slot("P2", 0)["unit_id"])
        self.assertIn("ST01-008", " ".join(stack.state.get_player_state("P2")["trash"]))
        # command 卡用畢進自己廢棄區
        self.assertIn("st01/ST01-012", stack.state.get_player_state("P1")["trash"])

    def test_command_card_not_offered_without_target(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.set_hand("P1", ["st01/ST01-012"])
        stack.put_unit("P2", "st01/ST01-008", 0, status="active")  # 沒有 rested 目標
        commands = stack.enumerator.legal_commands("P1")
        self.assertNotIn("play_card st01/ST01-012", commands)

    # ------------------------------------------------------------------
    # <Repair 2>：回合結束觸發治療
    # ------------------------------------------------------------------

    def test_repair_heals_at_end_of_turn(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        slot = stack.put_unit("P1", "st01/ST01-001", 0)
        slot["damage"] = 3

        stack.runtime.resolve_command(stack.parse("pass", "P1"))  # main → end/action
        # end/action：雙方讓過
        stack.runtime.resolve_command(stack.parse("pass", "P2"))
        stack.runtime.resolve_command(stack.parse("pass", "P1"))

        self.assertEqual(stack.state.get_slot("P1", 0)["damage"], 1)
        # 回合已輪替到 P2
        self.assertEqual(stack.state.get_active_player(), "P2")

    # ------------------------------------------------------------------
    # Pairing：[When Paired (White Base Team) pilot]Draw 1 + Link
    # ------------------------------------------------------------------

    def test_pairing_trait_conditional_draw_and_link(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.set_hand("P1", ["st01/ST01-010"])
        stack.put_unit("P1", "st01/ST01-002", 0, turns_on_field=0)  # link: Amuro Ray
        hand_before = len(stack.state.get_player_state("P1")["hand"])
        deck_before = len(stack.state.get_player_state("P1")["deck"])

        parsed = stack.parse("pair st01/ST01-010 my_slot_0", "P1")
        stack.runtime.resolve_command(parsed)

        slot = stack.state.get_slot("P1", 0)
        self.assertEqual(slot["pilot_id"], "st01/ST01-010")
        self.assertTrue(slot["is_link"])
        self.assertEqual(slot["ap"], 4 + 2)  # ST01-002 AP4 + Amuro AP2
        # Amuro 是 White Base Team → ST01-002 抽 1；Amuro 自身 [When Paired] rest 效果無目標落空
        self.assertEqual(len(stack.state.get_player_state("P1")["deck"]), deck_before - 1)
        self.assertEqual(len(stack.state.get_player_state("P1")["hand"]), hand_before - 1 + 1)
        # Link Unit 部署當回合可攻擊
        self.assertTrue(stack.state.can_attack_with_unit("P1", 0))

    def test_pairing_without_trait_no_draw(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.set_hand("P1", ["st01/ST01-011"])  # Suletta：非 White Base Team
        stack.put_unit("P1", "st01/ST01-002", 0)
        deck_before = len(stack.state.get_player_state("P1")["deck"])
        stack.runtime.resolve_command(stack.parse("pair st01/ST01-011 my_slot_0", "P1"))
        self.assertEqual(len(stack.state.get_player_state("P1")["deck"]), deck_before)
        self.assertFalse(stack.state.get_slot("P1", 0)["is_link"])

    # ------------------------------------------------------------------
    # 連續效果：ST01-001 [During Pair] 我方全體 AP+1（自己回合）
    # ------------------------------------------------------------------

    def test_during_pair_continuous_ap(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.set_hand("P1", ["st01/ST01-010"])
        stack.put_unit("P1", "st01/ST01-001", 0)  # 3/4, link Amuro
        stack.put_unit("P1", "st01/ST01-005", 1)  # 2/2
        stack.runtime.resolve_command(stack.parse("pair st01/ST01-010 my_slot_0", "P1"))
        # Amuro [When Paired] rest 效果：對手無單位 → 落空
        self.assertIsNone(stack.state.peek_pending_choice())
        # 配對後：ST01-001 base3 + pilot2 + cont1 = 6；ST01-005 2 + 1 = 3
        self.assertEqual(stack.state.get_slot("P1", 0)["ap"], 6)
        self.assertEqual(stack.state.get_slot("P1", 1)["ap"], 3)

    # ------------------------------------------------------------------
    # 攻擊規則 + 戰鬥 + Blocker + Burst
    # ------------------------------------------------------------------

    def test_attack_only_rested_units_and_base(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.put_unit("P1", "st01/ST01-005", 0)
        stack.put_unit("P2", "st01/ST01-005", 0, status="active")
        stack.put_unit("P2", "st01/ST01-008", 1, status="rested")
        commands = stack.enumerator.legal_commands("P1")
        self.assertIn("attack my_slot_0 opponent_base", commands)
        self.assertIn("attack my_slot_0 opponent_slot_1", commands)
        self.assertNotIn("attack my_slot_0 opponent_slot_0", commands)

    def test_st01_009_cannot_attack_player(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.put_unit("P1", "st01/ST01-009", 0)
        commands = stack.enumerator.legal_commands("P1")
        self.assertNotIn("attack my_slot_0 opponent_base", commands)
        with self.assertRaises(ValueError):
            stack.runtime.resolve_command(stack.parse("attack my_slot_0 opponent_base", "P1"))

    def test_battle_with_blocker(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.put_unit("P1", "st01/ST01-005", 0)            # 2/2 attacker
        stack.put_unit("P2", "st01/ST01-008", 0)            # 1/1 Blocker
        stack.runtime.resolve_command(stack.parse("attack my_slot_0 opponent_base", "P1"))
        # 防守方有 blocker → block step
        self.assertEqual(stack.state.get_step(), "block")
        self.assertEqual(stack.state.get_priority_player(), "P2")
        stack.runtime.resolve_command(stack.parse("block my_slot_0", "P2"))
        # battle action step：雙方讓過
        self.assertEqual(stack.state.get_step(), "action")
        stack.runtime.resolve_command(stack.parse("pass", "P2"))
        stack.runtime.resolve_command(stack.parse("pass", "P1"))
        # blocker 1/1 被 2AP 擊破；attacker 受 1 傷
        self.assertIsNone(stack.state.get_slot("P2", 0)["unit_id"])
        self.assertEqual(stack.state.get_slot("P1", 0)["damage"], 1)
        # 盾牌未受損
        self.assertEqual(len(stack.state.get_player_state("P2")["shield"]), 6)

    def test_attack_base_then_shield_burst_pilot(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.put_unit("P1", "st01/ST01-005", 0)  # 2/2
        p2 = stack.state.get_player_state("P2")
        p2["base"] = None  # 移除 EX base，直接打盾
        p2["shield"] = ["st01/ST01-010"] + p2["shield"][1:]  # 第一面盾是 Amuro（[Burst] 加入手牌）
        stack.set_hand("P2", [])

        stack.runtime.resolve_command(stack.parse("attack my_slot_0 opponent_base", "P1"))
        # P2 沒有 blocker → 直接 battle action step
        self.assertEqual(stack.state.get_step(), "action")
        stack.runtime.resolve_command(stack.parse("pass", "P2"))
        stack.runtime.resolve_command(stack.parse("pass", "P1"))
        # burst optional choice
        pending = stack.state.peek_pending_choice()
        self.assertIsNotNone(pending)
        self.assertEqual(pending["type"], "optional_effect")
        self.assertEqual(pending["player_id"], "P2")
        stack.runtime.resolve_pending_choice(stack.parse("choose activate", "P2"), pending)
        self.assertIn("st01/ST01-010", stack.state.get_player_state("P2")["hand"])
        self.assertEqual(len(p2["shield"]), 5)

    def test_burst_decline_goes_to_trash(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.put_unit("P1", "st01/ST01-005", 0)
        p2 = stack.state.get_player_state("P2")
        p2["base"] = None
        p2["shield"] = ["st01/ST01-010"] + p2["shield"][1:]
        stack.set_hand("P2", [])
        stack.runtime.resolve_command(stack.parse("attack my_slot_0 opponent_base", "P1"))
        stack.runtime.resolve_command(stack.parse("pass", "P2"))
        stack.runtime.resolve_command(stack.parse("pass", "P1"))
        pending = stack.state.peek_pending_choice()
        stack.runtime.resolve_pending_choice(stack.parse("choose decline", "P2"), pending)
        self.assertIn("st01/ST01-010", p2["trash"])
        self.assertNotIn("st01/ST01-010", p2["hand"])

    def test_zero_ap_does_not_break_shield(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        slot = stack.put_unit("P1", "st01/ST01-005", 0)
        slot["temp_ap_mod"] = -2
        stack.state.recompute_slot_stats(slot)
        p2 = stack.state.get_player_state("P2")
        p2["base"] = None
        shields_before = len(p2["shield"])
        stack.runtime.resolve_command(stack.parse("attack my_slot_0 opponent_base", "P1"))
        stack.runtime.resolve_command(stack.parse("pass", "P2"))
        stack.runtime.resolve_command(stack.parse("pass", "P1"))
        self.assertEqual(len(p2["shield"]), shields_before)

    # ------------------------------------------------------------------
    # [Attack][Once per Turn]：ST01-011 資源活化
    # ------------------------------------------------------------------

    def test_attack_trigger_set_resource_active_once(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.put_unit("P1", "st01/ST01-007", 0)  # link Suletta
        stack.set_hand("P1", ["st01/ST01-011"])
        stack.runtime.resolve_command(stack.parse("pair st01/ST01-011 my_slot_0", "P1"))
        resources = stack.state.get_player_state("P1")["resources"]
        # pair 花費 1 → rested 1
        self.assertEqual(resources["rested"], 1)
        stack.runtime.resolve_command(stack.parse("attack my_slot_0 opponent_base", "P1"))
        # [Attack] 觸發：1 個 rested 資源活化（自動綁定，不需選擇）
        self.assertEqual(resources["rested"], 0)
        self.assertEqual(resources["active"], 5)

    # ------------------------------------------------------------------
    # Base：部署、[Deploy] 盾牌進手、[Activate/Main] token 部署
    # ------------------------------------------------------------------

    def test_base_deploy_and_activate_token(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        p1 = stack.state.get_player_state("P1")
        p1["base"] = None  # EX base 已被摧毀，騰出基地區
        stack.set_hand("P1", ["st01/ST01-015"])
        hand_before = len(p1["hand"])

        stack.runtime.resolve_command(stack.parse("play_card st01/ST01-015", "P1"))
        base = stack.state.get_base("P1")
        self.assertEqual(base["card_id"], "st01/ST01-015")
        # [Deploy]：1 面盾進手牌（-1 出牌 +1 盾牌）
        self.assertEqual(len(p1["shield"]), 5)
        self.assertEqual(len(p1["hand"]), hand_before - 1 + 1)

        # [Activate/Main]（2）：場上 0 unit → Gundam token 3/3
        commands = stack.enumerator.legal_commands("P1")
        self.assertIn("activate_effect base", commands)
        stack.runtime.resolve_command(stack.parse("activate_effect base", "P1"))
        slot = stack.state.get_slot("P1", 0)
        self.assertIsNotNone(slot["unit_id"])
        self.assertTrue(slot["is_token"])
        self.assertEqual(slot["ap"], 3)
        # once per turn：不再出現
        self.assertNotIn("activate_effect base", stack.enumerator.legal_commands("P1"))

    def test_base_burst_deploys_base(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.put_unit("P1", "st01/ST01-005", 0)
        p2 = stack.state.get_player_state("P2")
        p2["base"] = None
        p2["shield"] = ["st01/ST01-016"] + p2["shield"][1:]
        stack.runtime.resolve_command(stack.parse("attack my_slot_0 opponent_base", "P1"))
        stack.runtime.resolve_command(stack.parse("pass", "P2"))
        stack.runtime.resolve_command(stack.parse("pass", "P1"))
        pending = stack.state.peek_pending_choice()
        self.assertEqual(pending["type"], "optional_effect")
        stack.runtime.resolve_pending_choice(stack.parse("choose activate", "P2"), pending)
        base = stack.state.get_base("P2")
        self.assertEqual(base["card_id"], "st01/ST01-016")
        # 連鎖 [Deploy]：再從盾牌補 1 張進手（5 - 1 = 4）
        self.assertEqual(len(p2["shield"]), 4)

    # ------------------------------------------------------------------
    # 勝負：直擊玩家
    # ------------------------------------------------------------------

    def test_player_damage_wins(self):
        stack = self.stack
        stack.start_midgame(active_player="P1")
        stack.put_unit("P1", "st01/ST01-005", 0)
        p2 = stack.state.get_player_state("P2")
        p2["base"] = None
        p2["shield"] = []
        stack.runtime.resolve_command(stack.parse("attack my_slot_0 opponent_base", "P1"))
        stack.runtime.resolve_command(stack.parse("pass", "P2"))
        stack.runtime.resolve_command(stack.parse("pass", "P1"))
        self.assertTrue(stack.runtime.is_game_over())
        self.assertEqual(stack.runtime.get_winner(), "P1")


if __name__ == "__main__":
    unittest.main()
