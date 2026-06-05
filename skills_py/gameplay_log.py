from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from .game_state import GameState, PlayerState


PROJECT_ROOT = Path(__file__).parent.parent.absolute()
GAME_STATES_DIR = PROJECT_ROOT / "game-states"
SCHEMA_VERSION = 1


def gameplay_log_path(game_id: str) -> Path:
    return GAME_STATES_DIR / game_id / "gameplay.yaml"


def replay_path(game_id: str) -> Path:
    return GAME_STATES_DIR / game_id / "replay.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _phase_text(phase: str, step: Optional[str]) -> str:
    phase_names = {
        "pre-game": "調度",
        "start": "開始階段",
        "draw": "抽牌階段",
        "resource": "資源階段",
        "main": "主要階段",
        "battle": "戰鬥階段",
        "end": "結束階段",
    }
    step_names = {
        "attack": "攻擊宣言",
        "action": "動作子步驟",
        "block": "阻擋",
        "damage": "傷害",
        "battle_end": "戰鬥結束",
    }
    label = phase_names.get(phase, phase)
    if step:
        label = f"{label}/{step_names.get(step, step)}"
    return label


def _base_features(player: PlayerState) -> dict[str, Any]:
    return {
        "card_id": player.base.card_id,
        "ap": player.base.ap,
        "hp": max(player.base.hp - player.base.damage, 0),
        "alive": player.base.alive,
    }


def _board_features(player: PlayerState) -> dict[str, int]:
    units = [slot for slot in player.battle_area if slot.unit_id is not None]
    return {
        "units": len(units),
        "empty_slots": 6 - len(units),
        "rested_units": sum(1 for slot in units if slot.status == "rested"),
        "damaged_units": sum(1 for slot in units if slot.damage > 0),
        "blockers": sum(1 for slot in units if "Blocker" in slot.keywords),
    }


def public_features(state: GameState) -> dict[str, Any]:
    return {
        "active_player": state.active_player,
        "priority": state.priority,
        "p1": _player_public_features(state.p1),
        "p2": _player_public_features(state.p2),
    }


def _player_public_features(player: PlayerState) -> dict[str, Any]:
    return {
        "hand_count": player.hand_count,
        "resources": {
            "active": player.resources_active,
            "rested": player.resources_rested,
            "ex": player.resources_ex,
        },
        "board": _board_features(player),
        "shields": player.shields,
        "base": _base_features(player),
    }


def _load_log(state: GameState) -> dict[str, Any]:
    path = gameplay_log_path(state.game_id)
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            loaded.setdefault("events", [])
            return loaded
    now = _now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "game_id": state.game_id,
        "created_at": now,
        "updated_at": now,
        "summary": {
            "first_player": state.first_player,
            "winner": state.winner,
            "final_turn": state.turn if state.game_over else None,
        },
        "events": [],
    }


def _write_log(state: GameState, data: dict[str, Any]) -> None:
    path = gameplay_log_path(state.game_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    data["summary"] = {
        "first_player": state.first_player,
        "winner": state.winner,
        "final_turn": state.turn if state.game_over else None,
    }
    tmp_path = path.with_suffix(".yaml.tmp")
    tmp_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def append_event(
    state: GameState,
    event_type: str,
    actor: Optional[str],
    viewer: str,
    message: str,
    *,
    command: Optional[str] = None,
    result: Optional[dict[str, Any]] = None,
    legal_actions: Optional[list[str]] = None,
    ai_evaluation: Optional[dict[str, Any]] = None,
    include_features: bool = True,
) -> dict[str, Any]:
    data = _load_log(state)
    seq = len(data.get("events", [])) + 1
    event: dict[str, Any] = {
        "seq": seq,
        "ts": _now_iso(),
        "turn": state.turn,
        "phase": state.phase,
        "step": state.step,
        "actor": actor,
        "viewer": viewer,
        "event_type": event_type,
        "message": message,
        "public": True,
    }
    if command is not None:
        event["command"] = command
    if result is not None:
        event["result"] = result
    if legal_actions is not None:
        event["legal_actions"] = legal_actions
    if ai_evaluation is not None:
        event["ai_evaluation"] = ai_evaluation
    if include_features:
        event["features"] = public_features(state)

    data.setdefault("events", []).append(event)
    _write_log(state, data)
    write_replay(state, data)
    return event


def append_checkpoint(state: GameState, viewer: str, message: str = "狀態檢查點") -> dict[str, Any]:
    return append_event(
        state,
        "state_checkpoint",
        state.priority or state.active_player,
        viewer,
        message,
        include_features=True,
    )


def read_events(state: GameState) -> list[dict[str, Any]]:
    return list(_load_log(state).get("events", []))


def _winner_text(winner: Optional[str]) -> str:
    return winner if winner else "尚未結束"


def write_replay(state: GameState, data: Optional[dict[str, Any]] = None) -> None:
    data = data or _load_log(state)
    path = replay_path(state.game_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# GCG 對局紀錄 - {state.game_id}",
        "",
        "## 摘要",
        f"- 先手：{state.first_player}",
        f"- 勝者：{_winner_text(state.winner)}",
        f"- 目前回合：{state.turn}",
        "",
        "## 時間線",
    ]
    events = data.get("events", [])
    if not events:
        lines.append("- 尚無事件。")
    for event in events:
        turn = event.get("turn", "?")
        phase = _phase_text(event.get("phase", ""), event.get("step"))
        lines.append(f"{event.get('seq', 0):03d}. 回合 {turn} / {phase} - {event.get('message', '')}")

    decision_events = [
        event for event in events
        if event.get("event_type") in {"decision_requested", "decision_received", "decision_applied", "ai_evaluation"}
    ]
    if decision_events:
        lines.extend(["", "## 決策 Review"])
        for event in decision_events:
            lines.extend([
                f"### 決策 {event.get('seq', 0):03d} - {event.get('actor') or '系統'}",
                f"- 狀態：回合 {event.get('turn', '?')}，{_phase_text(event.get('phase', ''), event.get('step'))}",
                f"- 事件：{event.get('message', '')}",
            ])
            if "command" in event:
                lines.append(f"- 指令：{event['command']}")
            if "legal_actions" in event:
                actions = ", ".join(event["legal_actions"]) if event["legal_actions"] else "未記錄"
                lines.append(f"- 可行選項：{actions}")
            result = event.get("result")
            if isinstance(result, dict):
                ok_text = "成功" if result.get("ok") else "失敗"
                reason = result.get("reason") or ""
                lines.append(f"- 結果：{ok_text}{f'，{reason}' if reason else ''}")
            lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
