#!/usr/bin/env python3
"""
AI-vs-AI replay harness for GCG.

Every player decision goes through the configured AI provider. The harness always
writes gameplay.yaml, replay.md, and a review.md under game-states/<game_id>/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills_py.game_engine import load_state
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded GCG AI-vs-AI replay harness")
    parser.add_argument("--max-turns", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--per-auto-actions", type=int, default=4)
    parser.add_argument("--max-ai-failures", type=int, default=1)
    parser.add_argument("--ai-timeout-seconds", type=float, default=60)
    parser.add_argument("--require-game-over", action="store_true")
    parser.add_argument("--first-player", choices=("P1", "P2"), default="P1")
    return parser.parse_args()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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


def _potential_attackers_next_turn(player_features: dict[str, Any]) -> int:
    board = player_features.get("board") if isinstance(player_features, dict) else {}
    slots = board.get("slots") if isinstance(board, dict) else []
    if not isinstance(slots, list):
        return 0
    attackers = 0
    for slot in slots:
        if not isinstance(slot, dict) or not slot.get("unit_id"):
            continue
        attackers += 1
    return attackers


def _blocker_count(player_features: dict[str, Any]) -> int:
    board = player_features.get("board") if isinstance(player_features, dict) else {}
    blockers = board.get("blockers") if isinstance(board, dict) else None
    return blockers if isinstance(blockers, int) else 0


def _lethal_race_deploy_signals(events: list[dict[str, Any]]) -> list[str]:
    signals: list[str] = []
    events_by_seq = {event.get("seq"): event for event in events}
    for event in events:
        if event.get("event_type") != "decision_received":
            continue
        if command_action(event.get("command", "")) != "deploy":
            continue
        actor = event.get("actor")
        if actor not in {"P1", "P2"}:
            continue
        opponent = "P2" if actor == "P1" else "P1"
        features = event.get("features") or {}
        actor_features = features.get(actor.lower()) or {}
        opponent_features = features.get(opponent.lower()) or {}
        base = actor_features.get("base") if isinstance(actor_features, dict) else {}
        if not isinstance(base, dict) or base.get("alive", True):
            continue
        shields = actor_features.get("shields")
        if not isinstance(shields, int):
            continue
        opponent_attackers = _potential_attackers_next_turn(opponent_features)
        if opponent_attackers <= shields:
            continue
        applied = events_by_seq.get((event.get("seq") or 0) + 1) or {}
        before_blockers = _blocker_count(actor_features)
        after_features = (applied.get("features") or {}).get(actor.lower()) or {}
        after_blockers = _blocker_count(after_features)
        if after_blockers <= before_blockers:
            signals.append(
                f"面臨下回合斬殺仍部署：seq {event.get('seq')} {actor} 選擇 {event.get('command')}，"
                f"對手可攻擊單位 {opponent_attackers} > 己方盾牌 {shields}，且 blocker 未增加。"
            )
    return signals


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
    signals.extend(_lethal_race_deploy_signals(events))
    return signals


def analyze(game_id: str, snapshots: list[dict[str, Any]], ai_adapter_calls: int, max_reached: bool) -> dict[str, Any]:
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
    if ai_adapter_calls < 2:
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


def write_review(game_id: str, analysis: dict[str, Any], ai_adapter_calls: int) -> Path:
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
    if any("面臨下回合斬殺仍部署" in signal for signal in passive_signals):
        likely_causes.append("AI prompt problem：AI 沒有在基地被摧毀後先做 lethal race check，面臨下回合斬殺仍選擇無法增加 blocker 的部署。")
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
        f"Replay/log quality: gameplay.yaml parsed, replay.md present, ai_adapter_calls={ai_adapter_calls}, provider_mode=configured, ai_failures={len(analysis['ai_failures'])}, missing_ai_evaluation={len(analysis['missing_ai_evaluation'])}, ai_latency_max={max(analysis['ai_latencies']) if analysis['ai_latencies'] else 0:.3f}s",
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
    original_active = ACTIVE_GAME_FILE.read_text(encoding="utf-8") if ACTIVE_GAME_FILE.exists() else None
    original_timeout = os.environ.get("GCG_AI_TIMEOUT_SECONDS")
    snapshots: list[dict[str, Any]] = []
    try:
        os.environ["GCG_AI_TIMEOUT_SECONDS"] = str(args.ai_timeout_seconds)
        started = json.loads(_start_game("P1", True, args.first_player))
        game_id = started["game_id"]
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

        ai_adapter_call_count = sum(
            1 for event in (snapshots[-1].get("all_events") or [])
            if event.get("event_type") in {"decision_received", "ai_failure"} and event.get("actor") in {"P1", "P2"}
        )
        analysis = analyze(game_id, snapshots, ai_adapter_call_count, max_reached)
        review_path = write_review(game_id, analysis, ai_adapter_call_count)
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
