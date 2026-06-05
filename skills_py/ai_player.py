import random
from .game_state import GameState, PlayerState
from .card_db import get_card_cost, get_card_type, get_card_level, get_card_ap, get_card_hp


def ai_decide_mulligan(state: GameState, player_id: str) -> str:
    player = state.get_player(player_id)
    if not player.hand_cards:
        return "keep"
    low_cost = sum(1 for c in player.hand_cards if get_card_cost(c) <= 2)
    if low_cost < 2:
        return "redraw"
    return "keep"


def ai_get_playable_cards(state: GameState, player_id: str) -> list[str]:
    player = state.get_player(player_id)
    playable = []
    for card_id in player.hand_cards:
        ctype = get_card_type(card_id)
        if ctype == "token":
            continue
        level = get_card_level(card_id)
        cost = get_card_cost(card_id)
        if player.level < level:
            continue
        available = player.resources_active + player.resources_ex
        if available < cost:
            continue
        playable.append(card_id)
    return playable


def ai_get_empty_slot(player: PlayerState) -> int:
    for s in player.battle_area:
        if s.unit_id is None:
            return s.slot
    return -1


def ai_decide_main_action(state: GameState, player_id: str) -> str:
    player = state.get_player(player_id)
    playable = ai_get_playable_cards(state, player_id)

    if playable:
        playable_units = [c for c in playable if get_card_type(c) == "unit"]
        if playable_units:
            playable_units.sort(key=lambda c: get_card_level(c), reverse=True)
            for card_id in playable_units:
                slot = ai_get_empty_slot(player)
                if slot >= 0:
                    return f"play {card_id} {slot}"
        playable_others = [c for c in playable if get_card_type(c) != "unit"]
        if playable_others:
            card_id = playable_others[0]
            return f"play {card_id}"

    for s in player.battle_area:
        if s.unit_id and s.status == "active" and s.ap > 0:
            if s.link or s.turns_on_field >= 1:
                return f"attack {s.slot}"

    return "pass"


def ai_decide_command(state: GameState, player_id: str) -> str:
    if state.phase == "pre-game":
        return ai_decide_mulligan(state, player_id)
    elif state.phase == "main":
        return ai_decide_main_action(state, player_id)
    elif state.phase == "battle" and state.step == "attack":
        return "pass"
    elif state.phase == "battle" and state.step == "action":
        return "pass"
    elif state.phase == "end" and state.step == "action":
        return "pass"
    else:
        return "pass"
