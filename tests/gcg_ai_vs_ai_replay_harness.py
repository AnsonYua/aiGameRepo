#!/usr/bin/env python3
"""
AI-vs-AI replay harness for GCG.

Default mode fakes the AI adapter while still enforcing that every AI
decision goes through the adapter path. Use --live-llm to call the
configured live provider. The harness always writes gameplay.yaml, replay.md, and a
review.md under game-states/<game_id>/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills_py import ai_player
from skills_py.ai_adapters import AIAdapterResult
from skills_py.card_db import get_card_type
from skills_py.game_engine import can_attack, can_attack_unit, can_block, can_play_card, load_state
from skills_py.gcg_runtime import _auto, _start_game


ACTIVE_GAME_FILE = PROJECT_ROOT / ".gcg_active_game"
GAME_STATES_DIR = PROJECT_ROOT / "game-states"
REQUIRED_REVIEW_FIELDS = [
    "Game",
    "Result",
    "Length",
    "Rules safety",
    "Hidden-info safety",
    "AI command diversity",
    "Combat quality",
    "Blocker usage",
    "Unit-target attack usage",
    "Pass/action-window quality",
    "Replay/log quality",
    "Problems",
    "Likely root cause",
    "Follow-up",
    "Verdict",
]
FAKE_GAME_ID: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded GCG AI-vs-AI replay harness")
    parser.add_argument("--live-llm", action="store_true", help="call configured live AI provider")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-steps", type=int, default=80)
    parser.add_argument("--per-auto-actions", type=int, default=6)
    parser.add_argument("--max-ai-failures", type=int, default=1)
    parser.add_argument("--ai-timeout-seconds", type=float, default=60)
    parser.add_argument("--require-game-over", action="store_true")
    parser.add_argument("--first-player", choices=("P1", "P2"), default="P1")
    return parser.parse_args()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def active_game_id() -> str:
    return ACTIVE_GAME_FILE.read_text(encoding="utf-8").strip()


def fake_consider(command: str) -> str:
    if command.startswith("attack") and " unit " in command:
        return "公開場面有可處理的橫置單位，優先交換場面。"
    if command.startswith("attack"):
        return "公開防禦層可被推進，選擇攻擊。"
    if command.startswith("block"):
        return "對手攻擊進入阻擋窗口，使用公開阻擋者保護防禦層。"
    if command.startswith("deploy"):
        return "公開場面需要建立單位，選擇部署。"
    if command == "keep":
        return "依調度階段的隱藏資訊評估後選擇此指令，細節不寫入公開 replay。"
    return "公開場面沒有更高價值行動，選擇讓過。"


def choose_fake_command(player_id: str) -> str:
    state = load_state(FAKE_GAME_ID or active_game_id())
    assert_true(state is not None, "fake AI could not load active state")
    assert state is not None
    player = state.get_player(player_id)
    opponent = state.get_opponent(player_id)

    if state.phase == "pre-game":
        return "keep"

    if state.phase == "battle" and state.step in ("attack", "block") and state.priority == player_id:
        for slot in player.battle_area:
            if can_block(state, player_id, slot.slot)[0]:
                return f"block {slot.slot}"
        return "pass"

    if state.phase in ("battle", "end") and state.step == "action":
        return "pass"

    if state.phase != "main" or state.active_player != player_id or state.priority != player_id:
        return "pass"

    for card_id in player.hand_cards:
        if get_card_type(card_id) == "unit" and can_play_card(state, player_id, card_id)[0]:
            return f"deploy {card_id}"

    for card_id in player.hand_cards:
        if get_card_type(card_id) == "base" and can_play_card(state, player_id, card_id)[0]:
            return f"deploy {card_id}"

    for attacker in player.battle_area:
        if not can_attack(state, player_id, attacker.slot)[0]:
            continue
        for target in opponent.battle_area:
            if not target.unit_id:
                continue
            remaining_hp = target.hp - target.damage
            if target.status == "rested" and attacker.ap >= remaining_hp:
                if can_attack_unit(state, player_id, attacker.slot, target.slot)[0]:
                    return f"attack {attacker.slot} unit {target.slot}"

    for attacker in player.battle_area:
        if can_attack(state, player_id, attacker.slot)[0]:
            return f"attack {attacker.slot}"

    for card_id in player.hand_cards:
        if get_card_type(card_id) == "pilot" and can_play_card(state, player_id, card_id)[0]:
            for slot in player.battle_area:
                if slot.unit_id and not slot.pilot_id:
                    return f"pair {card_id} {slot.slot}"

    return "pass"


def install_fake_adapter() -> tuple[Any, list[list[str]]]:
    calls: list[list[str]] = []
    original_get_adapter = ai_player.ai_adapters.get_ai_adapter

    class FakeAdapter:
        provider = "fake"

        def run(self, prompt: str, timeout_seconds: float) -> AIAdapterResult:
            calls.append(["fake-ai", "<prompt>"])
            match = re.search(r"^player_id:\s*(P[12])$", prompt, flags=re.MULTILINE)
            assert_true(match is not None, "AI prompt must include player_id")
            player_id = match.group(1) if match else "P1"
            command = choose_fake_command(player_id)
            return AIAdapterResult(
                stdout=f"CONSIDER: {fake_consider(command)}\nCOMMAND: {command}\n",
                returncode=0,
                elapsed_seconds=0.01,
                provider=self.provider,
                argv=["fake-ai", "<prompt>"],
            )

    def fake_get_adapter(provider: str | None = None) -> FakeAdapter:
        return FakeAdapter()

    ai_player.ai_adapters.get_ai_adapter = fake_get_adapter
    return original_get_adapter, calls


def restore_adapter(original_get_adapter: Any) -> None:
    ai_player.ai_adapters.get_ai_adapter = original_get_adapter


def run_auto_step(game_id: str, player_id: str, per_auto_actions: int) -> dict[str, Any]:
    return json.loads(_auto(player_id, "P1", True, game_id, per_auto_actions))


def current_actor(snapshot: dict[str, Any]) -> str | None:
    priority = snapshot.get("priority")
    active = snapshot.get("active_player")
    phase = snapshot.get("phase")
    if priority in {"P1", "P2"}:
        return priority
    if phase == "main" and active in {"P1", "P2"}:
        return active
    return active if active in {"P1", "P2"} else None


def command_action(command: str) -> str:
    parts = command.split()
    if not parts:
        return "empty"
    action = parts[0].lower()
    if action in {"attack", "攻擊"} and "unit" in [part.lower() for part in parts]:
        return "attack_unit"
    if action in {"attack", "攻擊"}:
        return "attack_base"
    if action in {"block", "阻擋"}:
        return "block"
    if action in {"deploy", "play", "部署", "使用"}:
        return "deploy"
    if action in {"pass", "讓過"}:
        return "pass"
    return action


def ai_failure_count(snapshot: dict[str, Any]) -> int:
    return sum(1 for event in snapshot.get("all_events") or [] if event.get("event_type") == "ai_failure")


def load_artifacts(game_id: str) -> tuple[dict[str, Any], str]:
    game_dir = GAME_STATES_DIR / game_id
    gameplay_path = game_dir / "gameplay.yaml"
    replay_path = game_dir / "replay.md"
    assert_true(gameplay_path.exists(), f"missing gameplay log: {gameplay_path}")
    assert_true(replay_path.exists(), f"missing replay: {replay_path}")
    gameplay = yaml.safe_load(gameplay_path.read_text(encoding="utf-8"))
    replay = replay_path.read_text(encoding="utf-8")
    assert_true(isinstance(gameplay, dict), "gameplay.yaml must parse as mapping")
    return gameplay, replay


def _defense_total(event: dict[str, Any], player_id: str) -> int | None:
    features = event.get("features") or {}
    player = features.get(player_id.lower())
    if not isinstance(player, dict):
        return None
    shields = player.get("shields")
    base = player.get("base") or {}
    hp = base.get("hp")
    alive = base.get("alive")
    if not isinstance(shields, int):
        return None
    if alive and isinstance(hp, int):
        return shields + hp
    return shields


def _defense_progress(events: list[dict[str, Any]]) -> dict[str, Any]:
    previous: dict[str, int] = {}
    decreases: list[dict[str, Any]] = []
    for event in events:
        for player_id in ("p1", "p2"):
            total = _defense_total(event, player_id)
            if total is None:
                continue
            old = previous.get(player_id)
            if old is not None and total < old:
                decreases.append({
                    "seq": event.get("seq"),
                    "player": player_id.upper(),
                    "from": old,
                    "to": total,
                    "message": event.get("message", ""),
                })
            previous[player_id] = total
    return {
        "damage_events": decreases,
        "damage_event_count": len(decreases),
        "last_damage_seq": decreases[-1]["seq"] if decreases else None,
    }


def _max_consecutive_action(commands: list[str], action: str) -> int:
    best = 0
    current = 0
    for command in commands:
        if command_action(command) == action:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _passive_quality_signals(events: list[dict[str, Any]], ai_events: list[dict[str, Any]], commands: list[str]) -> list[str]:
    signals: list[str] = []
    action_counts = Counter(command_action(command) for command in commands)
    defense = _defense_progress(events)
    max_pass_chain = _max_consecutive_action(commands, "pass")
    if max_pass_chain >= 3:
        signals.append(f"連續 pass 過多：最多連續 {max_pass_chain} 次 AI pass。")
    if action_counts.get("attack_base", 0) == 0:
        signals.append("沒有觀察到推進防禦層的 attack base。")
    if defense["damage_event_count"] == 0 and len(ai_events) >= 6:
        signals.append("多次 AI 決策後沒有任何基地/盾牌防禦層下降。")

    deploy_with_board = 0
    for event in ai_events:
        if command_action(event.get("command", "")) != "deploy":
            continue
        actor = (event.get("actor") or "").lower()
        features = event.get("features") or {}
        actor_features = features.get(actor) or {}
        board = actor_features.get("board") or {}
        units = board.get("units")
        if isinstance(units, int) and units >= 2:
            deploy_with_board += 1
    if deploy_with_board >= 3:
        signals.append(f"已有場面後仍多次部署：{deploy_with_board} 次 deploy 發生在自己場上已有至少 2 個單位時。")
    return signals


def analyze(game_id: str, snapshots: list[dict[str, Any]], opencode_calls: int, max_reached: bool) -> dict[str, Any]:
    gameplay, replay = load_artifacts(game_id)
    events = gameplay.get("events", [])
    seqs = [event.get("seq") for event in events]
    ai_events = [
        event for event in events
        if event.get("event_type") == "decision_received" and event.get("actor") in {"P1", "P2"} and event.get("command")
    ]
    missing_ai_evaluation = [
        event for event in ai_events
        if not isinstance(event.get("ai_evaluation"), dict)
    ]
    ai_failures = [event for event in events if event.get("event_type") == "ai_failure"]
    applied_events = [event for event in events if event.get("event_type") == "decision_applied"]
    commands = [event.get("command", "") for event in ai_events]
    action_counts = Counter(command_action(command) for command in commands)
    defense_progress = _defense_progress(events)
    passive_quality_signals = _passive_quality_signals(events, ai_events, commands)
    illegal = [
        event for event in applied_events
        if isinstance(event.get("result"), dict) and not event["result"].get("ok", True)
    ]
    considerations = []
    ai_latencies = []
    for event in ai_events:
        ai_eval = event.get("ai_evaluation") or {}
        consideration = ai_eval.get("consideration")
        if consideration:
            considerations.append(consideration)
        elapsed = ai_eval.get("elapsed_seconds")
        if isinstance(elapsed, (int, float)):
            ai_latencies.append(float(elapsed))

    hidden_leaks = []
    for key in ("hand_cards", "deck_cards", "shield_cards"):
        if key in replay:
            hidden_leaks.append(f"replay contains {key}")
    for consideration in considerations:
        if "st01/" in consideration or "gd01/" in consideration or "手牌" in consideration:
            hidden_leaks.append(f"unsafe consideration: {consideration}")

    final = snapshots[-1] if snapshots else {}
    game_over = bool(final.get("game_over"))
    winner = final.get("winner")
    incomplete = max_reached and not game_over
    hard_failures = []
    if seqs != list(range(1, len(seqs) + 1)):
        hard_failures.append("event seq is not monotonic")
    if hidden_leaks:
        hard_failures.extend(hidden_leaks)
    if illegal:
        hard_failures.append(f"illegal commands: {len(illegal)}")
    if ai_failures:
        hard_failures.append(f"AI failures: {len(ai_failures)}")
    if missing_ai_evaluation:
        hard_failures.append(f"AI decisions missing ai_evaluation: {len(missing_ai_evaluation)}")
    turn_backtracks = []
    previous_turn = None
    for event in events:
        turn = event.get("turn")
        if previous_turn is not None and isinstance(turn, int) and turn < previous_turn:
            turn_backtracks.append((event.get("seq"), previous_turn, turn, event.get("message", "")))
        if isinstance(turn, int):
            previous_turn = turn
    if turn_backtracks:
        hard_failures.append(f"turn timeline backtracks: {turn_backtracks}")
    if not ai_events:
        hard_failures.append("no AI decision events")
    if opencode_calls < 2:
        hard_failures.append("AI adapter was not used for both players")

    return {
        "gameplay": gameplay,
        "replay": replay,
        "events": events,
        "ai_events": ai_events,
        "commands": commands,
        "action_counts": action_counts,
        "defense_progress": defense_progress,
        "passive_quality_signals": passive_quality_signals,
        "illegal": illegal,
        "ai_failures": ai_failures,
        "missing_ai_evaluation": missing_ai_evaluation,
        "turn_backtracks": turn_backtracks,
        "considerations": considerations,
        "ai_latencies": ai_latencies,
        "hidden_leaks": hidden_leaks,
        "game_over": game_over,
        "winner": winner,
        "incomplete": incomplete,
        "hard_failures": hard_failures,
        "final": final,
    }


def write_review(game_id: str, analysis: dict[str, Any], opencode_calls: int, live_llm: bool) -> Path:
    action_counts = analysis["action_counts"]
    ai_events = analysis["ai_events"]
    problems = []
    if analysis["incomplete"]:
        problems.append("對局達到 harness 上限，標記為 incomplete；這是需要 review replay 的 bug/quality signal，不可只調高上限。")
    if analysis["ai_failures"]:
        problems.append(f"AI 決策失敗 {len(analysis['ai_failures'])} 次，必須視為 fail/incomplete。")
    if analysis["missing_ai_evaluation"]:
        problems.append(f"有 {len(analysis['missing_ai_evaluation'])} 個 AI decision 缺少 ai_evaluation，可能走到非 AI 邊界。")
    if analysis["turn_backtracks"]:
        problems.append(f"事件時間線回退：{analysis['turn_backtracks']}")
    if analysis["ai_latencies"]:
        slow = [latency for latency in analysis["ai_latencies"] if latency >= 10]
        if slow:
            problems.append(f"AI 決策延遲偏高：max={max(analysis['ai_latencies']):.2f}s，>=10s 次數={len(slow)}。")
    if action_counts.get("attack_unit", 0) == 0:
        problems.append("本場未觀察到 attack unit；若有橫置敵方單位仍未使用，需檢查 prompt/display。")
    if action_counts.get("block", 0) == 0:
        problems.append("本場未觀察到 block；若有可阻擋窗口仍未使用，需檢查 prompt/runtime。")
    if not problems:
        problems.append("未發現硬性 replay/log 問題。")

    passive_signals = analysis.get("passive_quality_signals") or []
    problems.extend(passive_signals)

    likely_causes = []
    if analysis["incomplete"] and not analysis["ai_failures"] and not analysis["illegal"]:
        likely_causes.append("AI strategy quality bug：AI 指令合法但未在上限內有效推進勝利；必須回看 replay 判斷是 AI player prompt 還是 display command surface 問題。")
    if action_counts.get("attack_base", 0) == 0 or action_counts.get("attack_unit", 0) == 0 or action_counts.get("block", 0) == 0:
        likely_causes.append("AI prompt problem 或 Display problem：先檢查 replay/display 是否列出具體 ✅ attack/block 指令；有列出但 AI 不選才改 AI prompt。")
    if analysis["illegal"]:
        likely_causes.append("Runtime problem 或 command surface problem：AI 輸出指令後 runtime 拒絕，需檢查 runtime/engine 與 display 指令格式。")
    if analysis["ai_failures"]:
        likely_causes.append("Provider / adapter / prompt parse problem：AI 決策失敗，先看錯誤分類與 provider stdout/stderr。")
    if analysis["ai_latencies"]:
        slow = [latency for latency in analysis["ai_latencies"] if latency >= 10]
        if slow:
            likely_causes.append("provider CLI/model latency problem：單次 live LLM 決策偏慢；速度問題不能用 retry 或 Python fallback 掩蓋。")
    if not likely_causes:
        likely_causes.append("未發現明確 root cause；下一步仍需抽查 replay 中 pass/deploy/attack/block 的決策點。")

    if analysis["hard_failures"]:
        verdict = "FAIL"
    elif analysis["incomplete"]:
        verdict = "INCOMPLETE"
    else:
        verdict = "PASS"

    lines = [
        f"Game: {game_id}",
        f"Result: {'game_over' if analysis['game_over'] else 'incomplete'} / winner={analysis['winner'] or 'none'}",
        f"Length: {len(analysis['events'])} events, {len(ai_events)} AI decisions",
        f"Rules safety: {'FAIL: ' + '; '.join(analysis['hard_failures']) if analysis['hard_failures'] else 'PASS: no illegal applied commands detected'}",
        f"Hidden-info safety: {'FAIL: ' + '; '.join(analysis['hidden_leaks']) if analysis['hidden_leaks'] else 'PASS: no hidden-info leak detected in replay considerations/raw keys'}",
        f"AI command diversity: {dict(action_counts)}",
        f"Combat quality: attack_base={action_counts.get('attack_base', 0)}, attack_unit={action_counts.get('attack_unit', 0)}",
        f"Blocker usage: block={action_counts.get('block', 0)}",
        f"Unit-target attack usage: attack_unit={action_counts.get('attack_unit', 0)}",
        f"Pass/action-window quality: pass={action_counts.get('pass', 0)}, auto_pass_events={sum(1 for event in analysis['events'] if '自動讓過' in event.get('message', ''))}",
        f"Defense progress: damage_events={analysis['defense_progress']['damage_event_count']}, last_damage_seq={analysis['defense_progress']['last_damage_seq'] or 'none'}",
        f"Passive-play signals: {passive_signals if passive_signals else 'none'}",
        f"Replay/log quality: gameplay.yaml parsed, replay.md present, opencode_agent_calls={opencode_calls}, live_llm={live_llm}, ai_failures={len(analysis['ai_failures'])}, missing_ai_evaluation={len(analysis['missing_ai_evaluation'])}, ai_latency_max={max(analysis['ai_latencies']) if analysis['ai_latencies'] else 0:.3f}s",
        "Problems:",
        *[f"- {problem}" for problem in problems],
        "Likely root cause:",
        *[f"- {cause}" for cause in likely_causes],
        "Follow-up:",
        "- 先讀 replay.md 找出 AI pass/deploy 但沒有推進勝利的決策點；若 display 有具體 ✅ command 而 AI 不選，改 AI player prompt / Codex prompt。",
        "- 若 display 沒有列出具體 ✅ attack/block 指令，先改 gcg_display.py，不要先怪 AI。",
        "- 只有 review 證明上限太低、且 AI 持續正常推進防禦層時，才調高 max_turns/max_steps/max_actions。",
        f"Verdict: {verdict}",
        "",
    ]
    path = GAME_STATES_DIR / game_id / "review.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_harness(args: argparse.Namespace) -> tuple[str, Path, str]:
    global FAKE_GAME_ID
    original_active = ACTIVE_GAME_FILE.read_text(encoding="utf-8") if ACTIVE_GAME_FILE.exists() else None
    original_run = None
    original_timeout = os.environ.get("GCG_AI_TIMEOUT_SECONDS")
    opencode_calls: list[list[str]] = []
    snapshots: list[dict[str, Any]] = []
    try:
        if not args.live_llm:
            original_run, opencode_calls = install_fake_adapter()
        os.environ["GCG_AI_TIMEOUT_SECONDS"] = str(args.ai_timeout_seconds)
        started = json.loads(_start_game("P1", True, args.first_player))
        game_id = started["game_id"]
        FAKE_GAME_ID = game_id
        snapshots.append(started)

        first = run_auto_step(game_id, args.first_player, args.per_auto_actions)
        snapshots.append(first)

        max_reached = False
        for _ in range(args.max_steps):
            latest = snapshots[-1]
            if ai_failure_count(latest) >= args.max_ai_failures:
                max_reached = True
                break
            if latest.get("game_over"):
                break
            if latest.get("phase") == "main" and latest.get("active_player") in {"P1", "P2"}:
                state = load_state(game_id)
                if state and state.turn > args.max_turns:
                    max_reached = True
                    break
            actor = current_actor(latest)
            if actor not in {"P1", "P2"}:
                max_reached = True
                break
            next_snapshot = run_auto_step(game_id, actor, args.per_auto_actions)
            snapshots.append(next_snapshot)
            if ai_failure_count(next_snapshot) >= args.max_ai_failures:
                max_reached = True
                break
        else:
            max_reached = True

        if args.live_llm:
            opencode_call_count = sum(
                1 for event in (snapshots[-1].get("all_events") or [])
                if event.get("event_type") in {"decision_received", "ai_failure"} and event.get("actor") in {"P1", "P2"}
            )
        else:
            opencode_call_count = len(opencode_calls)
        analysis = analyze(game_id, snapshots, opencode_call_count, max_reached)
        review_path = write_review(game_id, analysis, opencode_call_count, args.live_llm)
        if args.require_game_over and not analysis["game_over"]:
            print(f"AI-vs-AI replay harness FAIL: {game_id}")
            print(f"Review: {review_path}")
            raise AssertionError("AI-vs-AI harness did not reach game_over")
        if analysis["hard_failures"]:
            print(f"AI-vs-AI replay harness FAIL: {game_id}")
            print(f"Review: {review_path}")
            raise AssertionError("; ".join(analysis["hard_failures"]))
        return game_id, review_path, "INCOMPLETE" if analysis["incomplete"] else "PASS"
    finally:
        if original_run is not None:
            restore_adapter(original_run)
        FAKE_GAME_ID = None
        if original_active is None:
            ACTIVE_GAME_FILE.unlink(missing_ok=True)
        else:
            ACTIVE_GAME_FILE.write_text(original_active, encoding="utf-8")
        if original_timeout is None:
            os.environ.pop("GCG_AI_TIMEOUT_SECONDS", None)
        else:
            os.environ["GCG_AI_TIMEOUT_SECONDS"] = original_timeout


def main() -> None:
    args = parse_args()
    try:
        game_id, review_path, verdict = run_harness(args)
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"AI-vs-AI replay harness {verdict}: {game_id}")
    print(f"Review: {review_path}")


if __name__ == "__main__":
    main()
