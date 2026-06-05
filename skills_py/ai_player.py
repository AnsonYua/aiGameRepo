import os
import subprocess
from pathlib import Path
from typing import Optional

from .game_engine import save_state
from .game_engine import can_attack, can_play_card
from .game_state import GameState
from .gcg_display import render
from .card_db import get_card_type


PROJECT_ROOT = Path(__file__).parent.parent.absolute()


def _state_path(state: GameState) -> Path:
    return PROJECT_ROOT / "game-states" / state.game_id / "gameState.md"


def _fallback_command(state: GameState, player_id: str, allowed: Optional[set[str]] = None) -> str:
    player = state.get_player(player_id)

    def allowed_action(action: str) -> bool:
        return allowed is None or action in allowed

    if state.phase == "main" and state.active_player == player_id and state.priority == player_id:
        for card_type in ("unit", "base"):
            if not allowed_action("deploy"):
                break
            for card_id in player.hand_cards:
                if get_card_type(card_id) == card_type and can_play_card(state, player_id, card_id)[0]:
                    return f"deploy {card_id}"

        if allowed_action("pair"):
            for card_id in player.hand_cards:
                if get_card_type(card_id) != "pilot" or not can_play_card(state, player_id, card_id)[0]:
                    continue
                for slot in player.battle_area:
                    if slot.unit_id is not None:
                        return f"pair {card_id} {slot.slot}"

        if allowed_action("play"):
            for card_id in player.hand_cards:
                if get_card_type(card_id) == "command" and can_play_card(state, player_id, card_id)[0]:
                    return f"play {card_id}"

        if allowed_action("attack"):
            for slot in player.battle_area:
                if can_attack(state, player_id, slot.slot)[0]:
                    return f"attack {slot.slot}"

    return "pass"


def ai_decide_command(state: GameState, player_id: str, allowed: Optional[set[str]] = None) -> str:
    if os.environ.get("CODEX_SHELL") and os.environ.get("GCG_USE_OPENCODE_AI") != "1":
        return _fallback_command(state, player_id, allowed)

    save_state(state)
    display_text = render(str(_state_path(state)), viewer=player_id)
    prompt = "\n".join([
        f"player_id: {player_id}",
        f"first_player: {state.first_player}",
        "",
        display_text,
    ])

    try:
        completed = subprocess.run(
            ["opencode", "run", "--agent", "gcg-ai-player", prompt],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        return _fallback_command(state, player_id, allowed)
    except subprocess.TimeoutExpired as exc:
        return _fallback_command(state, player_id, allowed)

    if completed.returncode != 0:
        return _fallback_command(state, player_id, allowed)

    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return _fallback_command(state, player_id, allowed)

    cmd = lines[-1]
    action = cmd.split(maxsplit=1)[0].lower()
    if allowed and action not in allowed:
        return _fallback_command(state, player_id, allowed)
    return cmd
