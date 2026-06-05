#!/usr/bin/env python3
"""
gcg_bootstrap.py — Single-shot game initialization.
Replaces the orchestrator's 6-step "start game" manual tool calls.

Usage:
  python skills_py/gcg_bootstrap.py [--json] [--display]

Outputs JSON to stdout with game_id, state_path, card_data.
With --display, also renders the mulligan template to /tmp/gcg_output.txt.
"""
import json
import random
import sys
import yaml
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
GAME_STATES_DIR = PROJECT_ROOT / "game-states"
ACTIVE_GAME_FILE = PROJECT_ROOT / ".gcg_active_game"

sys.path.insert(0, str(PROJECT_ROOT))

from skills_py.game_state import GameState, PlayerState, BattleSlot, BaseState
from skills_py.card_db import get_deck, build_card_summary


def init_game(game_id: str) -> GameState:
    state = GameState()
    state.game_id = game_id
    state.turn = 1

    first = random.choice(["P1", "P2"])
    state.first_player = first
    state.active_player = first
    state.phase = "pre-game"
    state.step = None
    state.priority = first
    state.p1.player_id = "P1"
    state.p2.player_id = "P2"

    second_player = "P2" if first == "P1" else "P1"

    for pid, deck_key in [("P1", "playerId_1"), ("P2", "playerId_2")]:
        player = state.get_player(pid)
        deck = get_deck(deck_key)
        random.shuffle(deck)
        player.hand_cards = deck[:5]
        player.deck_cards = deck[5:]
        player.deck_count = len(player.deck_cards)
        player.resource_deck_count = 10
        player.resources_active = 0
        player.resources_rested = 0
        player.shields = 0
        player.shield_cards = []
        player.battle_area = [BattleSlot(slot=i) for i in range(6)]
        player.trash = []
        player.removal = []
        player.base = BaseState()
        player.resources_ex = 1 if pid == second_player else 0

    state.battle_log.append(f"{first} started game as first player [CR-1.1]")
    return state


def save_state(state: GameState, state_path: str):
    game_dir = Path(state_path).parent
    game_dir.mkdir(parents=True, exist_ok=True)

    d = state.to_dict("P1")
    with open(state_path, "w") as f:
        yaml.dump(d, f, allow_unicode=True, default_flow_style=False)

    ACTIVE_GAME_FILE.write_text(state.game_id)


def build_card_data(state: GameState) -> dict:
    all_hand_cards = set(state.p1.hand_cards + state.p2.hand_cards)
    return {cid: build_card_summary(cid) for cid in all_hand_cards}


def main():
    random.seed()

    game_id = f"game_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    state_path = f"game-states/{game_id}/gameState.md"

    state = init_game(game_id)
    save_state(state, state_path)
    card_data = build_card_data(state)

    result = {
        "game_id": game_id,
        "state_path": state_path,
        "card_data": card_data,
        "priority": state.priority,
        "phase": state.phase,
        "first_player": state.first_player,
        "active_player": state.active_player,
    }

    use_json = "--json" in sys.argv
    want_display = "--display" in sys.argv

    if want_display:
        from skills_py.gcg_display import render
        output = render(state_path)
        display_path = "/tmp/gcg_output.txt"
        Path(display_path).write_text(output)
        result["display_written"] = display_path

    if use_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"game_id: {game_id}")
        print(f"state_path: {state_path}")
        print(f"phase: {state.phase}")
        print(f"first_player: {state.first_player}")
        print(f"active_player: {state.active_player}")
        print(f"priority: {state.priority}")


if __name__ == "__main__":
    main()
