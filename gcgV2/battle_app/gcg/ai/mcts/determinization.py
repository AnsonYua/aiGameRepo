"""Viewer-safe belief state construction for MCTS.

This module intentionally does not accept StateStore. Hidden zones are sampled
from deck composition and public information only.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import random

UNKNOWN_CARD = "__UNKNOWN_CARD__"
SHIELD_CARD = "__SHIELD_CARD__"


def determinize_for_observer(viewer_state, deck_config, observer_id, rng=None, deck_id="deck001"):
    """Build a synthetic full state from a viewer-safe state."""
    rng = rng or random
    state = {
        "game_id": viewer_state.get("game_id"),
        "turn": viewer_state.get("turn", 0),
        "phase": viewer_state.get("phase"),
        "step": viewer_state.get("step"),
        "active_player": viewer_state.get("active_player"),
        "priority_player": viewer_state.get("priority_player"),
        "action_window": {
            "active": False,
            "origin": None,
            "consecutive_passes": 0,
            "last_action_player": None,
        },
        "battle_context": deepcopy(viewer_state.get("battle_context")),
        "game_over": bool(viewer_state.get("game_over")),
        "winner": viewer_state.get("winner"),
        "win_reason": viewer_state.get("win_reason"),
        "players": {},
        "pending_choice": [deepcopy(viewer_state.get("pending_choice"))]
        if (viewer_state.get("pending_choice") or {}).get("visible")
        else [],
        "trigger_queue": [],
        "once_per_turn_used": [],
    }
    for player_id in ("P1", "P2"):
        player_deck_id = deck_id.get(player_id, "deck001") if isinstance(deck_id, dict) else deck_id
        state["players"][player_id] = _build_player_state(
            viewer_state, deck_config, observer_id, player_id, rng, player_deck_id,
        )
    return state


def _build_player_state(viewer_state, deck_config, observer_id, player_id, rng, deck_id):
    visible = viewer_state["players"][player_id]
    hand_count = int(visible.get("hand_count") or 0)
    shield_count = int(visible.get("shield_count") or 0)
    known_hand = list(visible.get("hand") or []) if player_id == observer_id else []

    pool = build_deck_counter(deck_config, deck_id)
    known_public = collect_public_counter(viewer_state, player_id)
    known_private = Counter(known_hand)
    remaining = _positive_counter(pool - known_public - known_private)

    if player_id == observer_id:
        hand = known_hand
    else:
        hand = sample_from_counter(remaining, min(hand_count, total_count(remaining)), rng)
        remaining = _positive_counter(remaining - Counter(hand))
        if len(hand) < hand_count:
            hand.extend([UNKNOWN_CARD] * (hand_count - len(hand)))

    shield = sample_from_counter(remaining, min(shield_count, total_count(remaining)), rng)
    remaining = _positive_counter(remaining - Counter(shield))
    if len(shield) < shield_count:
        shield.extend([SHIELD_CARD] * (shield_count - len(shield)))

    deck = expand_counter(remaining)
    rng.shuffle(deck)
    raw_deck_count = visible.get("deck_count")
    deck_count = len(deck) if raw_deck_count is None else int(raw_deck_count)
    if len(deck) < deck_count:
        deck.extend([UNKNOWN_CARD] * (deck_count - len(deck)))
    elif len(deck) > deck_count:
        deck = deck[:deck_count]

    return {
        "player_id": player_id,
        "hand": hand,
        "deck": deck,
        "shield": shield,
        "resource_deck_count": int(visible.get("resource_deck_count") or 0),
        "tokens": [],
        "resources": deepcopy(visible.get("resources") or {"active": 0, "rested": 0, "ex": 0}),
        "base": _base_from_viewer(visible.get("base")),
        "battle_area": [_slot_from_viewer(slot) for slot in visible.get("battle_area") or []],
        "trash": list(visible.get("trash") or []),
        "removal": list(visible.get("removal") or []),
        "temp_shield_damage_prevention": [],
    }


def build_deck_counter(deck_config, deck_id="deck001"):
    return Counter(deck_config.get_deck(deck_id)["main_deck"])


def collect_public_counter(viewer_state, player_id):
    visible = viewer_state["players"][player_id]
    known = []
    base = visible.get("base") or {}
    if base.get("present") and base.get("card_id") not in {None, "EX-BASE"}:
        known.append(base.get("card_id"))
    for zone in ("trash", "removal"):
        known.extend(card_id for card_id in visible.get(zone) or [] if card_id)
    for slot in visible.get("battle_area") or []:
        if slot.get("empty"):
            continue
        for key in ("unit_id", "pilot_id"):
            if slot.get(key):
                known.append(slot[key])
    return Counter(known)


def sample_from_counter(counter, count, rng=None):
    rng = rng or random
    cards = expand_counter(counter)
    if count <= 0 or not cards:
        return []
    return rng.sample(cards, min(count, len(cards)))


def expand_counter(counter):
    cards = []
    for card_id, amount in counter.items():
        cards.extend([card_id] * max(0, int(amount)))
    return cards


def total_count(counter):
    return sum(max(0, int(amount)) for amount in counter.values())


def _positive_counter(counter):
    return Counter({card_id: amount for card_id, amount in counter.items() if amount > 0})


def _base_from_viewer(base):
    base = base or {}
    if not base.get("present"):
        return None
    hp = int(base.get("hp") or 0)
    remaining = int(base.get("remaining_hp") or 0)
    return {
        "card_id": base.get("card_id"),
        "ap": int(base.get("ap") or 0),
        "hp": hp,
        "damage": max(0, hp - remaining),
        "alive": True,
        "status": base.get("status") or "active",
    }


def _slot_from_viewer(slot):
    if slot.get("empty"):
        return _empty_slot(slot.get("slot", 0))
    hp = int(slot.get("hp") or 0)
    remaining = int(slot.get("remaining_hp") or 0)
    return {
        "slot": int(slot.get("slot") or 0),
        "unit_id": slot.get("unit_id"),
        "pilot_id": slot.get("pilot_id"),
        "pilot_name": None,
        "ap": int(slot.get("ap") or 0),
        "hp": hp,
        "damage": max(0, hp - remaining),
        "status": slot.get("status") or "active",
        "keywords": list(slot.get("keywords") or []),
        "base_keywords": list(slot.get("base_keywords") or []),
        "temp_keywords": list(slot.get("temp_keywords") or []),
        "cont_keywords": list(slot.get("cont_keywords") or []),
        "temp_cannot_attack": bool(slot.get("temp_cannot_attack")),
        "temp_cannot_attack_player": bool(slot.get("temp_cannot_attack_player")),
        "cont_cannot_attack": bool(slot.get("cont_cannot_attack")),
        "cont_cannot_attack_player": bool(slot.get("cont_cannot_attack_player")),
        "temp_damage_prevention": bool(slot.get("temp_damage_prevention")),
        "is_link": bool(slot.get("is_link")),
        "turns_on_field": int(slot.get("turns_on_field") or 0),
    }


def _empty_slot(slot_index):
    return {
        "slot": int(slot_index or 0),
        "unit_id": None,
        "pilot_id": None,
        "pilot_name": None,
        "ap": 0,
        "hp": 0,
        "damage": 0,
        "status": None,
        "keywords": [],
        "base_keywords": [],
        "temp_keywords": [],
        "cont_keywords": [],
        "temp_cannot_attack": False,
        "temp_cannot_attack_player": False,
        "cont_cannot_attack": False,
        "cont_cannot_attack_player": False,
        "temp_damage_prevention": False,
        "is_link": False,
        "turns_on_field": 0,
    }
