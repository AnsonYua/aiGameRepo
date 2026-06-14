"""Command parser 與 spec gate 單元測試。"""

import unittest

from helpers import TestStack  # noqa: F401  (path side effect)

from gcg.effects.dictionary import EffectDictionary
from gcg.effects.spec_gate import SpecGate, SpecGateError
from gcg.engine.command_parser import CommandParser, parse_attack_target_ref, parse_slot_ref


class TestCommandParser(unittest.TestCase):
    def setUp(self):
        self.parser = CommandParser()

    def test_choose(self):
        parsed = self.parser.parse("choose go_first", "P1")
        self.assertEqual(parsed.command_type, "choose")
        self.assertEqual(parsed.choice_id, "go_first")
        self.assertEqual(parsed.command_line(), "choose go_first")

    def test_two_line_format(self):
        parsed = self.parser.parse("CONSIDER: 先建立場面。\nCOMMAND: play_card st01/ST01-008 0", "P1")
        self.assertEqual(parsed.command_type, "play_card")
        self.assertEqual(parsed.consider, "先建立場面。")
        self.assertEqual(parsed.command_line(), "play_card st01/ST01-008 0")

    def test_pair(self):
        parsed = self.parser.parse("pair st01/ST01-010 my_slot_2", "P1")
        self.assertEqual(parsed.command_type, "pair")
        self.assertEqual(parsed.target_ref, "my_slot_2")

    def test_attack_block_pass(self):
        attack = self.parser.parse("attack my_slot_0 opponent_base", "P1")
        self.assertEqual(attack.command_line(), "attack my_slot_0 opponent_base")
        block = self.parser.parse("block my_slot_1", "P2")
        self.assertEqual(block.command_line(), "block my_slot_1")
        self.assertEqual(self.parser.parse("end turn", "P1").command_type, "pass")

    def test_rejects_unknown(self):
        with self.assertRaises(ValueError):
            self.parser.parse("teleport my_slot_0", "P1")

    def test_slot_refs(self):
        self.assertEqual(parse_slot_ref("my_slot_3"), 3)
        self.assertEqual(parse_slot_ref("opponent_slot_0"), 0)
        self.assertEqual(parse_attack_target_ref("opponent_base"), ("base", None))
        self.assertEqual(parse_attack_target_ref("opponent_slot_2"), ("unit", 2))


class TestSpecGate(unittest.TestCase):
    def setUp(self):
        self.gate = SpecGate(EffectDictionary())

    def _valid_spec(self):
        return {
            "status": "resolved",
            "source_card_id": "ST01-012",
            "timing": "MAIN",
            "target_requirements": [
                {"name": "t1", "controller": "opponent", "card_type": "unit",
                 "status": "rested", "count": 1},
            ],
            "primitive_steps": [
                {"primitive": "damage", "target": "$t1", "amount": 1},
            ],
        }

    def test_accepts_valid_spec(self):
        self.gate.validate(self._valid_spec())

    def test_rejects_unknown_primitive(self):
        spec = self._valid_spec()
        spec["primitive_steps"][0]["primitive"] = "annihilate"
        with self.assertRaises(SpecGateError):
            self.gate.validate(spec)

    def test_rejects_unknown_target_reference(self):
        spec = self._valid_spec()
        spec["primitive_steps"][0]["target"] = "$nope"
        with self.assertRaises(SpecGateError):
            self.gate.validate(spec)

    def test_rejects_bad_timing_and_status(self):
        spec = self._valid_spec()
        spec["timing"] = "WHENEVER"
        with self.assertRaises(SpecGateError):
            self.gate.validate(spec)
        spec = self._valid_spec()
        spec["status"] = "maybe"
        with self.assertRaises(SpecGateError):
            self.gate.validate(spec)

    def test_rejects_unsupported_condition(self):
        spec = self._valid_spec()
        spec["primitive_steps"] = [{
            "primitive": "conditional",
            "condition": {"type": "moon_phase"},
            "steps": [{"primitive": "draw", "amount": 1}],
        }]
        with self.assertRaises(SpecGateError):
            self.gate.validate(spec)


if __name__ == "__main__":
    unittest.main()
