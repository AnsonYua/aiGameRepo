#!/usr/bin/env python3
"""
Regression harness for the GCG AI/runtime boundary.

This intentionally uses only stdlib assertions so it can run in any local
checkout without installing pytest. It does not call live opencode; the AI
adapter subprocess is faked to prove Python stays an adapter, not a strategy
engine.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills_py import ai_player
from skills_py.ai_player import _parse_ai_output, _public_safe_consideration, ai_decide
from skills_py.game_engine import init_game, save_state
from skills_py.game_state import BattleSlot, GameState
from skills_py.gcg_runtime import _handle_command


ACTIVE_GAME_FILE = PROJECT_ROOT / ".gcg_active_game"
GAME_STATES_DIR = PROJECT_ROOT / "game-states"


@dataclass
class FakeCompleted:
    stdout: str
    stderr: str = ""
    returncode: int = 0


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_main_state(game_id: str = "harness_ai_adapter") -> GameState:
    state = init_game(game_id)
    state.first_player = "P1"
    state.active_player = "P1"
    state.phase = "main"
    state.step = None
    state.priority = "P1"
    state.p1.hand_cards = ["st01/ST01-005"]
    state.p2.hand_cards = ["st01/ST01-008"]
    state.p1.deck_cards = []
    state.p2.deck_cards = []
    state.p1.shield_cards = []
    state.p2.shield_cards = []
    state.p1.resources_active = 2
    state.p1.resources_rested = 0
    state.p1.resources_ex = 0
    state.p2.resources_active = 0
    state.p2.resources_rested = 0
    state.p2.resources_ex = 1
    state.p1.shields = 6
    state.p2.shields = 6
    return state


def cleanup_harness_state() -> None:
    for path in GAME_STATES_DIR.glob("harness_*"):
        if path.is_dir():
            shutil.rmtree(path)


def test_ai_output_contract() -> None:
    parsed = _parse_ai_output("CONSIDER: 公開場面需保守處理\nCOMMAND: attack 0 unit 1\n")
    assert_true(parsed.command == "attack 0 unit 1", "COMMAND line should be parsed")
    assert_true(parsed.consideration == "公開場面需保守處理", "CONSIDER line should be parsed")


def test_ai_decide_uses_gcg_agent_and_reprompts_invalid_allowed() -> None:
    state = make_main_state()
    calls: list[list[str]] = []
    outputs = [
        "CONSIDER: 無法安全決策\nCOMMAND: pass\n",
        "CONSIDER: 依公開場面選擇保留\nCOMMAND: keep\n",
    ]
    original_run = ai_player.subprocess.run

    def fake_run(args: list[str], **kwargs: Any) -> FakeCompleted:
        calls.append(args)
        return FakeCompleted(stdout=outputs[len(calls) - 1])

    ai_player.subprocess.run = fake_run
    try:
        decision = ai_decide(state, "P1", {"keep", "redraw"})
    finally:
        ai_player.subprocess.run = original_run

    assert_true(decision.command == "keep", "AI adapter should reprompt invalid legal action")
    assert_true(len(calls) == 2, "AI adapter should retry once through gcg-ai-player")
    for call in calls:
        assert_true(call[:3] == ["opencode", "run", "--agent"], "AI adapter must call opencode agent")
        assert_true(call[3] == "gcg-ai-player", "AI adapter must use gcg-ai-player.md")


def test_consideration_sanitizer_blocks_hidden_info() -> None:
    state = make_main_state()
    text = "用 st01/ST01-005 和 GM 的手牌曲線建立優勢"
    sanitized = _public_safe_consideration(state, "P1", text)
    assert_true("st01/ST01-005" not in sanitized, "sanitizer must remove hidden card id")
    assert_true("GM" not in sanitized, "sanitizer must remove hidden card name")
    assert_true("手牌" not in sanitized, "sanitizer must not write hand details to public replay")


def test_runtime_attack_enemy_unit() -> None:
    state = make_main_state("harness_unit_attack")
    state.p1.battle_area[0] = BattleSlot(
        slot=0,
        unit_id="st01/ST01-005",
        ap=2,
        hp=2,
        damage=0,
        status="active",
        turns_on_field=1,
    )
    state.p2.battle_area[1] = BattleSlot(
        slot=1,
        unit_id="st01/ST01-008",
        ap=1,
        hp=1,
        damage=0,
        status="rested",
        keywords=["Blocker"],
        turns_on_field=1,
    )
    ok, reason = _handle_command(state, "P1", "attack 0 unit 1")
    assert_true(ok, f"unit-target attack should be legal: {reason}")
    assert_true(state.p2.battle_area[1].unit_id is None, "target unit should be destroyed")
    assert_true(state.phase == "main" and state.priority == "P1", "battle should return to main priority")


def test_runtime_block_command() -> None:
    state = make_main_state("harness_block")
    state.phase = "battle"
    state.step = "block"
    state.priority = "P2"
    state.current_attacker = 0
    state.p1.battle_area[0] = BattleSlot(
        slot=0,
        unit_id="st01/ST01-005",
        ap=2,
        hp=2,
        damage=0,
        status="active",
        turns_on_field=1,
    )
    state.p2.battle_area[1] = BattleSlot(
        slot=1,
        unit_id="st01/ST01-009",
        ap=3,
        hp=2,
        damage=0,
        status="active",
        keywords=["Blocker"],
        turns_on_field=1,
    )
    ok, reason = _handle_command(state, "P2", "block 1")
    assert_true(ok, f"block should be legal: {reason}")
    assert_true(state.p1.battle_area[0].unit_id is None, "attacker should be destroyed")
    assert_true(state.p2.battle_area[1].unit_id is None, "blocker should be destroyed")


def test_replay_yaml_public_safe_consideration() -> None:
    state = make_main_state("harness_replay")
    save_state(state)
    from skills_py.gameplay_log import append_event, gameplay_log_path, replay_path

    append_event(
        state,
        "decision_received",
        "P1",
        "P1",
        "P1 回傳指令：pass",
        command="pass",
        ai_evaluation={
            "chosen_command": "pass",
            "candidates": [],
            "consideration": "依公開場面、防禦層與優先權評估後選擇此指令。",
        },
    )
    loaded = yaml.safe_load(gameplay_log_path(state.game_id).read_text(encoding="utf-8"))
    assert_true(loaded["events"][0]["ai_evaluation"]["consideration"], "YAML should store consideration")
    replay = replay_path(state.game_id).read_text(encoding="utf-8")
    assert_true("- 考量：" in replay, "replay should render consideration")
    assert_true("st01/" not in replay, "replay consideration should not expose hidden card ids")


def test_live_llm_contract() -> None:
    state = init_game("harness_live_llm")
    state.first_player = "P1"
    state.active_player = "P1"
    state.priority = "P1"
    decision = ai_decide(state, "P1", {"keep", "redraw"})
    action = decision.command.split(maxsplit=1)[0].lower()
    assert_true(action in {"keep", "redraw"}, f"live LLM returned invalid mulligan command: {decision.command}")
    assert_true(decision.consideration != "", "live LLM should return CONSIDER")
    assert_true("st01/" not in decision.consideration, "live LLM CONSIDER must not expose card ids")
    assert_true("手牌" not in decision.consideration, "adapter must sanitize hidden hand wording")


def run(live_llm: bool = False) -> None:
    original_active = ACTIVE_GAME_FILE.read_text(encoding="utf-8") if ACTIVE_GAME_FILE.exists() else None
    try:
        cleanup_harness_state()
        test_ai_output_contract()
        test_ai_decide_uses_gcg_agent_and_reprompts_invalid_allowed()
        test_consideration_sanitizer_blocks_hidden_info()
        test_runtime_attack_enemy_unit()
        test_runtime_block_command()
        test_replay_yaml_public_safe_consideration()
        if live_llm:
            test_live_llm_contract()
    finally:
        cleanup_harness_state()
        if original_active is None:
            ACTIVE_GAME_FILE.unlink(missing_ok=True)
        else:
            ACTIVE_GAME_FILE.write_text(original_active, encoding="utf-8")
    suffix = " with live LLM." if live_llm else "."
    print(f"GCG direction harness passed{suffix}")


if __name__ == "__main__":
    run(live_llm="--live-llm" in sys.argv)
