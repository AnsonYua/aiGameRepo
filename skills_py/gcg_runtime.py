#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chat adapter runtime for Codex and opencode.

Players should interact through chat. This CLI is the stable internal boundary
used by chat adapters to mutate state and return full viewer-specific display.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "skills_py") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "skills_py"))

from skills_py.ai_adapters import probe_provider
from skills_py.ai_player import AIDecision, _parse_ai_output, ai_decide
from skills_py.game_engine import (
    can_block,
    can_attack_unit,
    can_play_card,
    cleanup_turn,
    declare_attack,
    determine_winner,
    end_battle,
    init_game,
    mulligan_keep,
    mulligan_redraw,
    pass_turn,
    play_card,
    resolve_block,
    resolve_unit_attack,
    resolve_unblocked_attack,
    save_state,
    setup_shields,
    start_phase,
    draw_phase,
    resource_phase,
)
from skills_py.game_state import GameState
from skills_py.card_db import get_card_type
from skills_py.gameplay_log import (
    append_checkpoint,
    append_event,
    gameplay_log_path,
    read_events,
    replay_path,
)
from gcg_display import render


GAME_STATES_DIR = PROJECT_ROOT / "game-states"
ACTIVE_GAME_FILE = PROJECT_ROOT / ".gcg_active_game"


def _state_path(game_id: str) -> Path:
    return GAME_STATES_DIR / game_id / "gameState.md"


def _active_game_id(game_id: Optional[str] = None) -> str:
    if game_id:
        return game_id
    if not ACTIVE_GAME_FILE.exists():
        raise RuntimeError("尚未開始遊戲。請先輸入 start game。")
    active_game_id = ACTIVE_GAME_FILE.read_text(encoding="utf-8").strip()
    if not active_game_id:
        raise RuntimeError(".gcg_active_game 是空的。請重新 start game。")
    return active_game_id


def _load_active_state(game_id: Optional[str] = None) -> GameState:
    game_id = _active_game_id(game_id)
    path = _state_path(game_id)
    if not path.exists():
        raise RuntimeError(f"找不到目前遊戲狀態：{path}")
    return GameState.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def _write_state(state: GameState) -> Path:
    save_state(state)
    return _state_path(state.game_id)


def _display(state: GameState, viewer: str) -> str:
    path = _write_state(state)
    return render(str(path), viewer=viewer)


def _record_event(
    state: GameState,
    events: list[dict],
    event_type: str,
    actor: Optional[str],
    viewer: str,
    message: str,
    **kwargs,
) -> None:
    event = append_event(state, event_type, actor, viewer, message, **kwargs)
    events.append(event)


def _record_game_end_if_needed(state: GameState, events: list[dict], viewer: str) -> None:
    if not state.game_over or not state.winner:
        return
    if any(event.get("event_type") == "game_end" for event in events):
        return
    reason = ""
    if state.battle_log:
        last_log = state.battle_log[-1]
        if "獲勝" in last_log or "投降" in last_log:
            reason = f"（{last_log}）"
    _record_event(state, events, "game_end", state.winner, viewer, f"遊戲結束，勝者：{state.winner}{reason}")


def _record_ai_failure(
    state: GameState,
    events: list[dict],
    player_id: str,
    viewer: str,
    exc: RuntimeError,
) -> None:
    message = f"{player_id} AI 決策失敗：{exc}"
    state.battle_log.append(message)
    _record_event(
        state,
        events,
        "ai_failure",
        player_id,
        viewer,
        message,
        result={"ok": False, "reason": str(exc)},
    )


def _format_battle_details(logs: list[str]) -> str:
    if not logs:
        return ""
    return "（" + "；".join(logs) + "）"


def _ai_evaluation(decision: AIDecision) -> dict:
    data = {"chosen_command": decision.command, "candidates": []}
    if decision.provider:
        data["provider"] = decision.provider
    if decision.consideration:
        data["consideration"] = decision.consideration
    if decision.elapsed_seconds:
        data["elapsed_seconds"] = round(decision.elapsed_seconds, 3)
    return data


def _ai_probe(provider: Optional[str], as_json: bool) -> str:
    try:
        result = probe_provider(provider)
    except Exception as exc:
        selected = provider or os.environ.get("GCG_AI_PROVIDER", "opencode")
        data = {
            "ok": False,
            "provider": selected,
            "returncode": None,
            "elapsed_seconds": 0,
            "argv": [],
            "stdout": "",
            "stderr": str(exc),
            "parse_error": "",
        }
        if as_json:
            return json.dumps(data, ensure_ascii=False, indent=2)
        return "\n".join([
            "AI provider probe FAIL",
            f"provider: {selected}",
            f"stderr: {exc}",
        ])
    parsed = None
    parse_error = ""
    if result.returncode == 0:
        try:
            parsed = _parse_ai_output(result.stdout)
        except RuntimeError as exc:
            parse_error = str(exc)
    ok = result.returncode == 0 and parsed is not None and parsed.command == "pass"
    data = {
        "ok": ok,
        "provider": result.provider,
        "returncode": result.returncode,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "argv": result.argv,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "parse_error": parse_error,
    }
    if as_json:
        return json.dumps(data, ensure_ascii=False, indent=2)
    status = "PASS" if ok else "FAIL"
    lines = [
        f"AI provider probe {status}",
        f"provider: {result.provider}",
        f"returncode: {result.returncode}",
        f"elapsed_seconds: {result.elapsed_seconds:.3f}",
    ]
    if result.stderr.strip():
        lines.append(f"stderr: {result.stderr.strip()}")
    if result.stdout.strip():
        lines.append("stdout:")
        lines.append(result.stdout.strip())
    if parse_error:
        lines.append(f"parse_error: {parse_error}")
    return "\n".join(lines)


def _result(
    state: GameState,
    viewer: str,
    as_json: bool = False,
    events: Optional[list[dict]] = None,
    checkpoint: bool = True,
) -> str:
    events = events if events is not None else []
    _auto_skip_empty_action_windows(state, viewer, events)
    if checkpoint:
        events.append(append_checkpoint(state, viewer, "輸出目前狀態"))
    text = _display(state, viewer)
    if not as_json:
        prefix = "\n".join(event["message"] for event in events)
        footer = f"Replay：{replay_path(state.game_id).relative_to(PROJECT_ROOT)}"
        if prefix:
            return f"{prefix}\n\n{text}\n{footer}"
        return f"{text}\n{footer}"
    return json.dumps({
        "game_id": state.game_id,
        "state_path": str(_state_path(state.game_id)),
        "replay_path": str(replay_path(state.game_id)),
        "gameplay_log_path": str(gameplay_log_path(state.game_id)),
        "viewer": viewer,
        "active_player": state.active_player,
        "priority": state.priority,
        "phase": state.phase,
        "step": state.step,
        "game_over": state.game_over,
        "winner": state.winner,
        "events": events,
        "all_events": read_events(state),
        "display_text": text,
    }, ensure_ascii=False, indent=2)


def _force_first_player(state: GameState, first_player: Optional[str]) -> None:
    """覆寫 init_game 的隨機先手，用 --first-player 指定。
    後手玩家獲得 1 EX 資源（CR-1.1）。"""
    if not first_player:
        return
    second_player = "P2" if first_player == "P1" else "P1"
    state.first_player = first_player
    state.active_player = first_player
    state.priority = first_player
    state.p1.resources_ex = 1 if second_player == "P1" else 0
    state.p2.resources_ex = 1 if second_player == "P2" else 0
    state.battle_log = [f"{first_player} 為先手 [CR-1.1]"]


def _start_game(viewer: str, as_json: bool, first_player: Optional[str]) -> str:
    game_id = f"game_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    state = init_game(game_id)
    _force_first_player(state, first_player)
    events: list[dict] = []
    _record_event(
        state,
        events,
        "game_start",
        None,
        viewer,
        f"遊戲開始，{state.first_player} 為先手",
    )
    return _result(state, viewer, as_json, events)


def _status(viewer: str, as_json: bool, game_id: Optional[str]) -> str:
    state = _load_active_state(game_id)
    checkpoint = not gameplay_log_path(state.game_id).exists()
    return _result(state, viewer, as_json, checkpoint=checkpoint)


def _advance_to_main_after_mulligan(state: GameState) -> None:
    setup_shields(state)
    start_phase(state)
    draw_phase(state)
    resource_phase(state)
    state.phase = "main"
    state.step = None
    state.priority = state.active_player


def _mulligan(player_id: str, action: str, viewer: str, as_json: bool, game_id: Optional[str]) -> str:
    state = _load_active_state(game_id)
    events: list[dict] = []
    if state.phase != "pre-game":
        return _result(state, viewer, as_json, events)

    if action == "redraw":
        mulligan_redraw(state, player_id)
        message = f"{player_id} 選擇重新調度"
    else:
        mulligan_keep(state, player_id)
        message = f"{player_id} 保留手牌"
    _record_event(
        state,
        events,
        "decision_applied",
        player_id,
        viewer,
        message,
        command=action,
        result={"ok": True, "reason": ""},
        legal_actions=["keep", "redraw"],
    )

    if player_id == "P1":
        _record_event(
            state,
            events,
            "decision_requested",
            "P2",
            viewer,
            "P2 正在決定調度...",
            legal_actions=["keep", "redraw"],
        )
        try:
            p2_decision = ai_decide(state, "P2", {"keep", "redraw"})
        except RuntimeError as exc:
            _record_ai_failure(state, events, "P2", viewer, exc)
            return _result(state, viewer, as_json, events)
        p2_cmd = p2_decision.command
        p2_action = p2_cmd.split(maxsplit=1)[0].lower()
        if p2_action == "redraw":
            mulligan_redraw(state, "P2")
            p2_message = "P2 選擇重新調度"
        else:
            mulligan_keep(state, "P2")
            p2_action = "keep"
            p2_message = "P2 保留手牌"
        _record_event(
            state,
            events,
            "decision_applied",
            "P2",
            viewer,
            p2_message,
            command=p2_action,
            result={"ok": True, "reason": ""},
            legal_actions=["keep", "redraw"],
            ai_evaluation=_ai_evaluation(AIDecision(
                command=p2_action,
                consideration=p2_decision.consideration,
                elapsed_seconds=p2_decision.elapsed_seconds,
                provider=p2_decision.provider,
            )),
        )
        _advance_to_main_after_mulligan(state)
        _record_event(state, events, "auto_progress", None, viewer, "調度完成，建立盾牌並進入先手主要階段")
    elif player_id == "P2":
        _advance_to_main_after_mulligan(state)
        _record_event(state, events, "auto_progress", None, viewer, "調度完成，建立盾牌並進入先手主要階段")

    if not state.game_over:
        _auto_resolve_p2(state, viewer=viewer, events=events)

    return _result(state, viewer, as_json, events)


def _handle_pass(state: GameState, player_id: str) -> tuple[bool, str]:
    if state.phase == "main" and player_id != state.active_player:
        return False, "不是你的主要階段。"
    if state.phase == "battle" and state.step in ("attack", "block"):
        if player_id != state.priority:
            return False, "目前不是你的阻擋優先權。"
        resolve_unblocked_attack(state)
        if not state.game_over:
            end_battle(state)
        return True, ""
    if state.phase == "battle" and state.step == "battle_end":
        end_battle(state)
        return True, ""
    if state.phase in ("end", "battle") and state.step == "action" and player_id != state.priority:
        return False, "目前不是你的優先權。"
    pass_turn(state, player_id)
    return True, ""


def _is_action_priority(state: GameState) -> bool:
    return (
        (state.phase == "end" and state.step == "action")
        or (state.phase == "battle" and state.step == "action")
    )


def _has_eligible_action_card(state: GameState, player_id: str) -> bool:
    player = state.get_player(player_id)
    for card_id in player.hand_cards:
        if get_card_type(card_id) != "command":
            continue
        ok, _ = can_play_card(state, player_id, card_id)
        if ok:
            return True
    return False


def _has_eligible_blocker(state: GameState, player_id: str) -> bool:
    return any(can_block(state, player_id, slot.slot)[0] for slot in state.get_player(player_id).battle_area)


def _auto_skip_empty_action_windows(
    state: GameState,
    viewer: str = "P1",
    events: Optional[list[dict]] = None,
    max_passes: int = 4,
) -> None:
    events = events if events is not None else []
    passes = 0
    while (
        not state.game_over
        and state.priority
        and _is_action_priority(state)
        and passes < max_passes
    ):
        player_id = state.priority
        if _has_eligible_action_card(state, player_id):
            break
        message = f"{player_id} 自動讓過：沒有可使用的 action card"
        state.battle_log.append(f"{player_id} 自動讓過（沒有可使用的 action card）")
        _record_event(state, events, "auto_progress", player_id, viewer, message)
        pass_turn(state, player_id)
        passes += 1


def _handle_command(state: GameState, player_id: str, cmd: str) -> tuple[bool, str]:
    parts = cmd.strip().split()
    if not parts:
        return True, ""

    action = parts[0].lower()
    if action in ("pass", "end", "endturn", "讓過"):
        return _handle_pass(state, player_id)

    if action in ("concede", "投降"):
        state.game_over = True
        state.winner = state.get_opponent(player_id).player_id
        state.battle_log.append(f"{player_id} 投降")
        return True, ""

    if action in ("play", "deploy", "部署", "使用") and len(parts) >= 2:
        slot: Optional[int] = None
        if len(parts) >= 3 and parts[2].isdigit():
            try:
                slot = int(parts[2])
            except ValueError:
                return False, f"非法欄位：{parts[2]}"
        return play_card(state, player_id, parts[1], slot)

    if action in ("pair", "配對") and len(parts) >= 3:
        try:
            slot = int(parts[2])
        except ValueError:
            return False, f"非法欄位：{parts[2]}"
        return play_card(state, player_id, parts[1], slot)

    if action in ("block", "阻擋") and len(parts) >= 2:
        if state.phase != "battle" or state.step not in ("attack", "block"):
            return False, "目前不能阻擋。"
        if player_id != state.priority:
            return False, "目前不是你的阻擋優先權。"
        try:
            slot = int(parts[1])
        except ValueError:
            return False, f"非法欄位：{parts[1]}"
        ok, reason = can_block(state, player_id, slot)
        if not ok:
            return False, reason
        resolve_block(state, slot)
        return True, ""

    if action in ("attack", "攻擊") and len(parts) >= 2:
        try:
            slot = int(parts[1])
        except ValueError:
            return False, f"非法欄位：{parts[1]}"
        target_slot: Optional[int] = None
        if len(parts) >= 3:
            target_token = parts[2].lower()
            if target_token in ("base", "基地", "shield", "盾牌", "player", "玩家"):
                target_slot = None
            elif target_token in ("unit", "enemy", "opponent", "單位", "敵方", "對手") and len(parts) >= 4:
                try:
                    target_slot = int(parts[3])
                except ValueError:
                    return False, f"非法目標欄位：{parts[3]}"
            elif parts[2].isdigit():
                target_slot = int(parts[2])
            else:
                return False, f"未知攻擊目標：{parts[2]}"
        if target_slot is not None:
            ok, reason = can_attack_unit(state, player_id, slot, target_slot)
            if not ok:
                return False, reason
            ok, reason = declare_attack(state, player_id, slot)
            if not ok:
                return False, reason
            resolve_unit_attack(state, target_slot)
            if not state.game_over:
                end_battle(state)
            return True, ""
        ok, reason = declare_attack(state, player_id, slot)
        if not ok:
            return False, reason
        defender_id = state.get_opponent(player_id).player_id
        state.step = "block"
        state.priority = defender_id
        if not _has_eligible_blocker(state, defender_id):
            resolve_unblocked_attack(state)
            if not state.game_over:
                end_battle(state)
        return True, ""

    return False, f"未知指令：{action}"


def _split_compound_commands(cmd: str) -> tuple[list[str], str]:
    parts = cmd.strip().split()
    if not parts:
        return [], ""

    commands: list[list[str]] = [[]]
    i = 0
    while i < len(parts):
        token = parts[i]
        token_lower = token.lower()
        if token_lower in {"and", "then", "然後"}:
            if not commands[-1]:
                return [], "複合指令格式錯誤：連接詞前缺少指令"
            if commands[-1]:
                commands.append([])
            if token_lower == "and" and i + 1 < len(parts) and parts[i + 1].lower() == "then":
                i += 1
            i += 1
            continue
        commands[-1].append(token)
        i += 1

    if not commands[-1]:
        return [], "複合指令格式錯誤：連接詞後缺少指令"

    return [" ".join(part) for part in commands], ""


def _auto_resolve_player(
    player_id: str,
    state: GameState,
    max_actions: int = 20,
    viewer: str = "P1",
    events: Optional[list[dict]] = None,
) -> None:
    events = events if events is not None else []
    actions = 0
    while not state.game_over and actions < max_actions:
        _auto_skip_empty_action_windows(state, viewer, events)
        if state.priority and state.priority != player_id:
            break
        if state.active_player != player_id and state.phase == "main":
            break
        try:
            _record_event(state, events, "decision_requested", player_id, viewer, f"{player_id} 正在思考...")
            decision = ai_decide(state, player_id)
            cmd = decision.command
        except RuntimeError as exc:
            _record_ai_failure(state, events, player_id, viewer, exc)
            break
        _record_event(
            state,
            events,
            "decision_received",
            player_id,
            viewer,
            f"{player_id} 回傳指令：{cmd}",
            command=cmd,
            ai_evaluation=_ai_evaluation(decision),
        )
        log_start = len(state.battle_log)
        ok, reason = _handle_command(state, player_id, cmd)
        details = _format_battle_details(state.battle_log[log_start:])
        actions += 1
        if not ok:
            message = f"{player_id} 指令失敗：{cmd}（{reason}）"
            state.battle_log.append(message)
            _record_event(
                state,
                events,
                "decision_applied",
                player_id,
                viewer,
                message,
                command=cmd,
                result={"ok": False, "reason": reason},
            )
            break
        _record_event(
            state,
            events,
            "decision_applied",
            player_id,
            viewer,
            f"{player_id} 執行：{cmd}{details}",
            command=cmd,
            result={"ok": True, "reason": ""},
        )
        determine_winner(state)
        _record_game_end_if_needed(state, events, viewer)
        if state.game_over:
            break
        _auto_skip_empty_action_windows(state, viewer, events)
        if cmd.startswith("pass") or state.priority != player_id:
            break


def _auto_resolve_p2(
    state: GameState,
    max_actions: int = 20,
    viewer: str = "P1",
    events: Optional[list[dict]] = None,
) -> None:
    _auto_resolve_player("P2", state, max_actions, viewer, events)


def _command(player_id: str, cmd: str, viewer: str, as_json: bool, game_id: Optional[str]) -> str:
    state = _load_active_state(game_id)
    events: list[dict] = []
    _record_event(state, events, "decision_received", player_id, viewer, f"{player_id} 輸入指令：{cmd}", command=cmd)
    ok = True
    reason = ""
    commands, reason = _split_compound_commands(cmd)
    if reason:
        ok = False
        state.battle_log.append(f"非法指令：{reason}")
        _record_event(
            state,
            events,
            "decision_applied",
            player_id,
            viewer,
            f"{player_id} 指令失敗：{cmd}",
            command=cmd,
            result={"ok": False, "reason": reason},
        )
    for sub_cmd in commands:
        log_start = len(state.battle_log)
        ok, reason = _handle_command(state, player_id, sub_cmd)
        details = _format_battle_details(state.battle_log[log_start:])
        if not ok:
            state.battle_log.append(f"非法指令：{reason}")
        _record_event(
            state,
            events,
            "decision_applied",
            player_id,
            viewer,
            f"{player_id} 指令{'成功' if ok else '失敗'}：{sub_cmd}{details if ok else ''}",
            command=sub_cmd,
            result={"ok": ok, "reason": reason},
        )
        if not ok:
            break
    determine_winner(state)
    if not state.game_over:
        _auto_resolve_p2(state, viewer=viewer, events=events)
    _record_game_end_if_needed(state, events, viewer)
    return _result(state, viewer, as_json, events)


def _auto(player_id: str, viewer: str, as_json: bool, game_id: Optional[str], max_actions: int = 20) -> str:
    state = _load_active_state(game_id)
    events: list[dict] = []
    if state.phase == "pre-game":
        _record_event(
            state,
            events,
            "decision_requested",
            player_id,
            viewer,
            f"{player_id} 正在決定調度...",
            legal_actions=["keep", "redraw"],
        )
        try:
            decision = ai_decide(state, player_id, {"keep", "redraw"})
        except RuntimeError as exc:
            _record_ai_failure(state, events, player_id, viewer, exc)
            return _result(state, viewer, as_json, events)
        cmd = decision.command
        action = cmd.split(maxsplit=1)[0].lower()
        if action == "redraw":
            mulligan_redraw(state, player_id)
            message = f"{player_id} 選擇重新調度"
        else:
            mulligan_keep(state, player_id)
            action = "keep"
            message = f"{player_id} 保留手牌"
        _record_event(
            state,
            events,
            "decision_applied",
            player_id,
            viewer,
            message,
            command=action,
            result={"ok": True, "reason": ""},
            legal_actions=["keep", "redraw"],
            ai_evaluation=_ai_evaluation(AIDecision(
                command=action,
                consideration=decision.consideration,
                elapsed_seconds=decision.elapsed_seconds,
                provider=decision.provider,
            )),
        )
        if player_id == "P1":
            _record_event(
                state,
                events,
                "decision_requested",
                "P2",
                viewer,
                "P2 正在決定調度...",
                legal_actions=["keep", "redraw"],
            )
            try:
                p2_decision = ai_decide(state, "P2", {"keep", "redraw"})
            except RuntimeError as exc:
                _record_ai_failure(state, events, "P2", viewer, exc)
                return _result(state, viewer, as_json, events)
            p2_cmd = p2_decision.command
            p2_action = p2_cmd.split(maxsplit=1)[0].lower()
            if p2_action == "redraw":
                mulligan_redraw(state, "P2")
                p2_message = "P2 選擇重新調度"
            else:
                mulligan_keep(state, "P2")
                p2_action = "keep"
                p2_message = "P2 保留手牌"
            _record_event(
                state,
                events,
                "decision_applied",
                "P2",
                viewer,
                p2_message,
                command=p2_action,
                result={"ok": True, "reason": ""},
                legal_actions=["keep", "redraw"],
                ai_evaluation=_ai_evaluation(AIDecision(
                    command=p2_action,
                    consideration=p2_decision.consideration,
                    elapsed_seconds=p2_decision.elapsed_seconds,
                    provider=p2_decision.provider,
                )),
            )
        _advance_to_main_after_mulligan(state)
        _record_event(state, events, "auto_progress", None, viewer, "調度完成，建立盾牌並進入先手主要階段")
    _auto_resolve_player(player_id, state, max_actions, viewer, events)
    _record_game_end_if_needed(state, events, viewer)
    return _result(state, viewer, as_json, events)


def main() -> None:
    parser = argparse.ArgumentParser(description="GCG chat adapter runtime")
    parser.add_argument("--json", action="store_true", help="輸出 JSON，display_text 仍是完整顯示文字")
    sub = parser.add_subparsers(dest="command_name", required=True)

    start = sub.add_parser("start")
    start.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    start.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    start.add_argument("--first-player", choices=("P1", "P2"), help="測試用：固定先手玩家")

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    status.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    status.add_argument("--game-id", help="內部測試/adapter 用：固定讀取指定 game_id")

    mulligan = sub.add_parser("mulligan")
    mulligan.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    mulligan.add_argument("--player", choices=("P1", "P2"), required=True)
    mulligan.add_argument("--action", choices=("keep", "redraw"), required=True)
    mulligan.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    mulligan.add_argument("--game-id", help="內部測試/adapter 用：固定讀取指定 game_id")

    command = sub.add_parser("command")
    command.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    command.add_argument("--player", choices=("P1", "P2"), required=True)
    command.add_argument("--cmd", required=True)
    command.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    command.add_argument("--game-id", help="內部測試/adapter 用：固定讀取指定 game_id")

    auto = sub.add_parser("auto")
    auto.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    auto.add_argument("--player", choices=("P1", "P2"), required=True)
    auto.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    auto.add_argument("--game-id", help="內部測試/adapter 用：固定讀取指定 game_id")
    auto.add_argument("--max-actions", type=int, default=20)

    ai_probe = sub.add_parser("ai-probe")
    ai_probe.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    ai_probe.add_argument("--provider", choices=("opencode", "codex", "claude"), help="測試指定 AI provider")

    args = parser.parse_args()

    try:
        if args.command_name == "start":
            output = _start_game(args.viewer, args.json, args.first_player)
        elif args.command_name == "status":
            output = _status(args.viewer, args.json, args.game_id)
        elif args.command_name == "mulligan":
            output = _mulligan(args.player, args.action, args.viewer, args.json, args.game_id)
        elif args.command_name == "command":
            output = _command(args.player, args.cmd, args.viewer, args.json, args.game_id)
        elif args.command_name == "auto":
            output = _auto(args.player, args.viewer, args.json, args.game_id, args.max_actions)
        elif args.command_name == "ai-probe":
            output = _ai_probe(args.provider, args.json)
        else:
            raise RuntimeError("未知 runtime 指令")
    except Exception as exc:
        output = f"非法指令：{exc}"

    print(output)


if __name__ == "__main__":
    main()
