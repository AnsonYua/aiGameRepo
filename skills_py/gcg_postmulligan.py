#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gcg_postmulligan.py — Apply redraws + start phase + display. JSON to stdout.

Usage:
  python3 skills_py/gcg_postmulligan.py <state_path> [--redraw-p1] [--redraw-p2]
"""
import argparse
import json
import random
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from skills_py.game_state import GameState
from skills_py.gcg_display import render


def apply_redraw(state: GameState, player_id: str, do_redraw: bool):
    player = state.get_player(player_id)
    if not do_redraw:
        return

    redrawn = list(player.hand_cards)
    kept = []

    player.deck_cards = player.deck_cards + redrawn
    random.shuffle(player.deck_cards)

    replacements = player.deck_cards[:len(redrawn)]
    player.deck_cards = player.deck_cards[len(redrawn):]
    player.hand_cards = kept + replacements
    player.deck_count = len(player.deck_cards)

    state.battle_log.append(f"{player_id} redrew all {len(redrawn)} cards")


def apply_start_phase(state: GameState):
    first = state.first_player
    active = state.active_player

    for pid in ("P1", "P2"):
        player = state.get_player(pid)
        shields = player.deck_cards[:6]
        player.deck_cards = player.deck_cards[6:]
        player.deck_count = len(player.deck_cards)
        player.shield_cards = shields
        player.shields = len(shields)

    state.phase = "start"
    state.step = None
    state.battle_log.append("Shields set [CR-2.4]")

    for pid in ("P1", "P2"):
        player = state.get_player(pid)
        player.resources_active = player.resources_active + player.resources_rested + player.resources_ex
        player.resources_rested = 0
        player.resources_ex = 0

    active_player = state.get_player(active)
    if active_player.deck_cards:
        card = active_player.deck_cards.pop(0)
        active_player.hand_cards.append(card)
        active_player.deck_count = len(active_player.deck_cards)
        state.battle_log.append(f"{active} draws a card [CR-2.5]")

    state.phase = "draw"

    if active_player.resource_deck_count > 0:
        active_player.resource_deck_count -= 1
        active_player.resources_active += 1
        state.battle_log.append(f"{active} deploys a resource [CR-2.6]")

    state.phase = "main"
    state.step = None
    state.priority = active


def main():
    ap = argparse.ArgumentParser(description="Deterministic post-mulligan: redraws + start phase + display")
    ap.add_argument("state_path", help="Path to gameState.md")
    ap.add_argument("--redraw-p1", action="store_true", help="P1 redraws all 5 hand cards")
    ap.add_argument("--redraw-p2", action="store_true", help="P2 redraws all 5 hand cards")
    args = ap.parse_args()

    random.seed()

    state = GameState.from_dict(yaml.safe_load(Path(args.state_path).read_text(encoding="utf-8")))

    apply_redraw(state, "P1", args.redraw_p1)
    apply_redraw(state, "P2", args.redraw_p2)

    apply_start_phase(state)

    state_path = str(Path(args.state_path).absolute())
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    d = state.to_dict("none")
    with open(state_path, "w") as f:
        yaml.dump(d, f, allow_unicode=True, default_flow_style=False)

    display_text = render(state_path)

    result = {
        "state_path": state_path,
        "priority": state.priority,
        "phase": state.phase,
        "active_player": state.active_player,
        "display_text": display_text,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
