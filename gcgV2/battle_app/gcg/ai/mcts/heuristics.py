"""Heuristics for MCTS evaluation and rollouts."""

from __future__ import annotations

import math
import random


def evaluate(state, observer_id):
    if state.get("game_over"):
        return 1.0 if state.get("winner") == observer_id else -1.0
    opponent = other_player(observer_id)
    score = 0.0
    score += 0.15 * (_base_ratio(state, observer_id) - _base_ratio(state, opponent))
    score += 0.10 * (_shield_ratio(state, observer_id) - _shield_ratio(state, opponent))
    score += 0.05 * (_unit_count(state, observer_id) - _unit_count(state, opponent))
    score += 0.05 * _normalized_diff(_active_ap(state, observer_id), _active_ap(state, opponent))
    score += 0.05 * _normalized_diff(_blockers(state, observer_id), _blockers(state, opponent))
    score += 0.03 * _normalized_diff(_hand_count(state, observer_id), _hand_count(state, opponent))
    return max(-1.0, min(1.0, score))


def choose_rollout_action(actions, state, player_id, card_database, rng=None, epsilon=0.15):
    rng = rng or random
    if not actions:
        return None
    if rng.random() < epsilon:
        return rng.choice(actions)
    return max(actions, key=lambda action: _action_score(action, state, player_id, card_database))


def _action_score(action, state, player_id, card_database):
    if action.startswith("attack ") and action.endswith(" opponent_base"):
        return 100 + _attack_ap(action, state, player_id)
    if action.startswith("attack "):
        return 80 + _target_ap(action, state, player_id)
    if action.startswith("block "):
        return 70
    if action.startswith("pair "):
        return 60 + _card_ap(action.split()[1], card_database)
    if action.startswith("play_card "):
        parts = action.split()
        card = card_database.get(parts[1]) or {}
        if card.get("cardType") == "unit":
            return 50 + int(card.get("ap") or 0) + int(card.get("hp") or 0)
        if card.get("cardType") == "base":
            return 45 + int(card.get("hp") or 0)
        if card.get("cardType") == "command":
            return 35
    if action.startswith("activate_effect"):
        return 40
    if action == "pass":
        return 0
    return 10


def _base_ratio(state, player_id):
    base = state["players"][player_id].get("base")
    if not base or not base.get("alive", True):
        return 0.0
    hp = int(base.get("hp") or 0)
    if hp <= 0:
        return 0.0
    return max(0.0, (hp - int(base.get("damage") or 0)) / hp)


def _shield_ratio(state, player_id):
    return min(1.0, len(state["players"][player_id].get("shield") or []) / 6.0)


def _unit_count(state, player_id):
    return sum(1 for slot in state["players"][player_id]["battle_area"] if slot.get("unit_id") is not None)


def _active_ap(state, player_id):
    return sum(
        int(slot.get("ap") or 0)
        for slot in state["players"][player_id]["battle_area"]
        if slot.get("unit_id") is not None and slot.get("status") == "active"
    )


def _blockers(state, player_id):
    return sum(
        1
        for slot in state["players"][player_id]["battle_area"]
        if slot.get("unit_id") is not None and "Blocker" in (slot.get("keywords") or [])
    )


def _hand_count(state, player_id):
    return len(state["players"][player_id].get("hand") or [])


def _normalized_diff(left, right):
    total = left + right
    if total <= 0:
        return 0.0
    return (left - right) / total


def _attack_ap(action, state, player_id):
    parts = action.split()
    slot = _slot_by_ref(state, player_id, parts[1])
    return int((slot or {}).get("ap") or 0)


def _target_ap(action, state, player_id):
    parts = action.split()
    opponent = other_player(player_id)
    slot = _slot_by_ref(state, opponent, parts[2])
    return int((slot or {}).get("ap") or 0)


def _slot_by_ref(state, player_id, ref):
    try:
        index = int(ref.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return None
    for slot in state["players"][player_id]["battle_area"]:
        if slot["slot"] == index:
            return slot
    return None


def _card_ap(card_id, card_database):
    card = card_database.get(card_id) or {}
    return int(card.get("ap") or 0)


def other_player(player_id):
    return "P2" if player_id == "P1" else "P1"
