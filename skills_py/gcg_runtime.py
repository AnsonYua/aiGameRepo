#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chat adapter runtime for Codex and opencode.

Players should interact through chat. This CLI is the stable internal boundary
used by chat adapters to mutate state and return full viewer-specific display.
"""

import argparse
import json
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

from skills_py.ai_player import ai_decide_command
from skills_py.game_engine import (
    cleanup_turn,
    declare_attack,
    determine_winner,
    end_battle,
    init_game,
    mulligan_keep,
    mulligan_redraw,
    pass_turn,
    play_card,
    resolve_unblocked_attack,
    save_state,
    setup_shields,
    start_phase,
    draw_phase,
    resource_phase,
)
from skills_py.game_state import GameState
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


def _display_existing(state: GameState, viewer: str) -> str:
    return render(str(_state_path(state.game_id)), viewer=viewer)


def _result(state: GameState, viewer: str, as_json: bool = False) -> str:
    text = _display(state, viewer)
    if not as_json:
        return text
    return json.dumps({
        "game_id": state.game_id,
        "state_path": str(_state_path(state.game_id)),
        "viewer": viewer,
        "active_player": state.active_player,
        "priority": state.priority,
        "phase": state.phase,
        "step": state.step,
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
    state.battle_log = [f"{first_player} started game as first player [CR-1.1]"]


def _start_game(viewer: str, as_json: bool, first_player: Optional[str]) -> str:
    game_id = f"game_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    state = init_game(game_id)
    _force_first_player(state, first_player)
    return _result(state, viewer, as_json)


def _status(viewer: str, as_json: bool, game_id: Optional[str]) -> str:
    state = _load_active_state(game_id)
    text = _display_existing(state, viewer)
    if not as_json:
        return text
    return json.dumps({
        "game_id": state.game_id,
        "state_path": str(_state_path(state.game_id)),
        "viewer": viewer,
        "active_player": state.active_player,
        "priority": state.priority,
        "phase": state.phase,
        "step": state.step,
        "display_text": text,
    }, ensure_ascii=False, indent=2)


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
    if state.phase != "pre-game":
        return _result(state, viewer, as_json)

    if action == "redraw":
        mulligan_redraw(state, player_id)
    else:
        mulligan_keep(state, player_id)

    if player_id == "P1":
        p2_cmd = ai_decide_command(state, "P2", {"keep", "redraw"})
        p2_action = p2_cmd.split(maxsplit=1)[0].lower()
        if p2_action == "redraw":
            mulligan_redraw(state, "P2")
        else:
            mulligan_keep(state, "P2")
        _advance_to_main_after_mulligan(state)
    elif player_id == "P2":
        _advance_to_main_after_mulligan(state)

    if not state.game_over:
        _auto_resolve_p2(state)

    return _result(state, viewer, as_json)


def _handle_pass(state: GameState, player_id: str) -> tuple[bool, str]:
    if state.phase == "main" and player_id != state.active_player:
        return False, "不是你的主要階段。"
    if state.phase == "end" and state.step == "action" and player_id != state.priority:
        return False, "目前不是你的優先權。"
    pass_turn(state, player_id)
    return True, ""


def _handle_command(state: GameState, player_id: str, cmd: str) -> tuple[bool, str]:
    parts = cmd.strip().split()
    if not parts:
        return True, ""

    action = parts[0].lower()
    if action in ("pass", "end", "讓過"):
        return _handle_pass(state, player_id)

    if action in ("concede", "投降"):
        state.game_over = True
        state.winner = state.get_opponent(player_id).player_id
        state.battle_log.append(f"{player_id} concedes")
        return True, ""

    if action in ("play", "deploy", "部署", "使用") and len(parts) >= 2:
        slot: Optional[int] = None
        if len(parts) >= 3:
            try:
                slot = int(parts[2])
            except ValueError:
                return False, f"非法欄位：{parts[2]}"
        return play_card(state, player_id, parts[1], slot)

    if action in ("attack", "攻擊") and len(parts) >= 2:
        try:
            slot = int(parts[1])
        except ValueError:
            return False, f"非法欄位：{parts[1]}"
        ok, reason = declare_attack(state, player_id, slot)
        if not ok:
            return False, reason
        # Current engine has no interactive block window in runtime yet; resolve
        # the attack immediately to preserve existing gcg_simulation behavior.
        resolve_unblocked_attack(state)
        end_battle(state)
        return True, ""

    return False, f"未知指令：{action}"


def _auto_resolve_p2(state: GameState, max_actions: int = 20) -> None:
    actions = 0
    while not state.game_over and actions < max_actions:
        if state.priority and state.priority != "P2":
            break
        if state.active_player != "P2" and state.phase == "main":
            break
        try:
            cmd = ai_decide_command(state, "P2")
        except RuntimeError as exc:
            state.battle_log.append(f"P2 AI failed: {exc}")
            break
        ok, reason = _handle_command(state, "P2", cmd)
        actions += 1
        if not ok:
            state.battle_log.append(f"P2 failed {cmd}: {reason}")
            break
        determine_winner(state)
        if cmd.startswith("pass") or state.priority != "P2":
            break


def _command(player_id: str, cmd: str, viewer: str, as_json: bool, game_id: Optional[str]) -> str:
    state = _load_active_state(game_id)
    ok, reason = _handle_command(state, player_id, cmd)
    if not ok:
        state.battle_log.append(f"非法指令：{reason}")
    determine_winner(state)
    if not state.game_over:
        _auto_resolve_p2(state)
    return _result(state, viewer, as_json)


def _auto(player_id: str, viewer: str, as_json: bool, game_id: Optional[str], max_actions: int = 20) -> str:
    state = _load_active_state(game_id)
    if player_id == "P2":
        _auto_resolve_p2(state, max_actions)
    return _result(state, viewer, as_json)


def main() -> None:
    parser = argparse.ArgumentParser(description="GCG chat adapter runtime")
    parser.add_argument("--json", action="store_true", help="輸出 JSON，display_text 仍是完整顯示文字")
    sub = parser.add_subparsers(dest="command_name", required=True)

    start = sub.add_parser("start")
    start.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    start.add_argument("--first-player", choices=("P1", "P2"), help="測試用：固定先手玩家")

    status = sub.add_parser("status")
    status.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    status.add_argument("--game-id", help="內部測試/adapter 用：固定讀取指定 game_id")

    mulligan = sub.add_parser("mulligan")
    mulligan.add_argument("--player", choices=("P1", "P2"), required=True)
    mulligan.add_argument("--action", choices=("keep", "redraw"), required=True)
    mulligan.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    mulligan.add_argument("--game-id", help="內部測試/adapter 用：固定讀取指定 game_id")

    command = sub.add_parser("command")
    command.add_argument("--player", choices=("P1", "P2"), required=True)
    command.add_argument("--cmd", required=True)
    command.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    command.add_argument("--game-id", help="內部測試/adapter 用：固定讀取指定 game_id")

    auto = sub.add_parser("auto")
    auto.add_argument("--player", choices=("P1", "P2"), required=True)
    auto.add_argument("--viewer", choices=("P1", "P2"), default="P1")
    auto.add_argument("--game-id", help="內部測試/adapter 用：固定讀取指定 game_id")
    auto.add_argument("--max-actions", type=int, default=20)

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
        else:
            raise RuntimeError("未知 runtime 指令")
    except Exception as exc:
        output = f"非法指令：{exc}"

    print(output)


if __name__ == "__main__":
    main()
