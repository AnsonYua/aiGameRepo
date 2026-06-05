import random
from typing import Optional, Tuple
from pathlib import Path

from .game_state import GameState, PlayerState, BattleSlot, BaseState
from .card_db import (
    get_card, get_card_name, get_card_type, get_card_level,
    get_card_cost, get_card_ap, get_card_hp, get_card_keywords,
    get_deck, build_card_summary
)

PROJECT_ROOT = Path(__file__).parent.parent.absolute() if "__file__" in dir() else Path("/Users/hello/Desktop/cardAI")
GAME_STATES_DIR = PROJECT_ROOT / "game-states"
ACTIVE_GAME_FILE = PROJECT_ROOT / ".gcg_active_game"


def init_game(game_id: str, p1_deck: str = "playerId_1", p2_deck: str = "playerId_2"):
    import random as rnd
    rnd.seed()

    state = GameState()
    state.game_id = game_id
    state.turn = 1
    first = rnd.choice(["P1", "P2"])
    state.first_player = first
    state.active_player = first
    state.phase = "pre-game"
    state.step = None
    state.priority = first
    state.p1.player_id = "P1"
    state.p2.player_id = "P2"

    for pid, deck_key in [("P1", p1_deck), ("P2", p2_deck)]:
        player = state.get_player(pid)
        deck = get_deck(deck_key)
        rnd.shuffle(deck)
        player.hand_cards = deck[:5]
        player.deck_cards = deck[5:]
        player.deck_count = len(player.deck_cards)
        player.resource_deck_count = 10
        player.resources_active = 0
        player.resources_rested = 0
        player.shields = 0
        player.battle_area = [BattleSlot(slot=i) for i in range(6)]
        player.trash = []
        player.removal = []
        player.base = BaseState()

    if first == "P1":
        state.p1.resources_ex = 0
        state.p2.resources_ex = 1
    else:
        state.p1.resources_ex = 1
        state.p2.resources_ex = 0

    state.battle_log.append(f"{first} started game as first player [CR-1.1]")
    return state


def save_state(state: GameState):
    import yaml
    game_dir = GAME_STATES_DIR / state.game_id
    game_dir.mkdir(parents=True, exist_ok=True)
    state_file = game_dir / "gameState.md"
    d = state.to_dict("P1")
    with open(state_file, "w") as f:
        yaml.dump(d, f, allow_unicode=True, default_flow_style=False)

    with open(ACTIVE_GAME_FILE, "w") as f:
        f.write(state.game_id)


def load_state(game_id: str) -> Optional[GameState]:
    import yaml
    state_file = GAME_STATES_DIR / game_id / "gameState.md"
    if not state_file.exists():
        return None
    with open(state_file) as f:
        d = yaml.safe_load(f)
    return GameState.from_dict(d)


def mulligan_redraw(state: GameState, player_id: str) -> GameState:
    player = state.get_player(player_id)
    all_cards = player.hand_cards + player.deck_cards
    random.shuffle(all_cards)
    player.hand_cards = all_cards[:5]
    player.deck_cards = all_cards[5:]
    player.deck_count = len(player.deck_cards)
    state.battle_log.append(f"{player_id} redraws")
    return state


def mulligan_keep(state: GameState, player_id: str) -> GameState:
    state.battle_log.append(f"{player_id} keeps")
    return state


def setup_shields(state: GameState):
    for pid in ["P1", "P2"]:
        player = state.get_player(pid)
        player.shields = 6
        player.shield_cards = player.deck_cards[:6]
        player.deck_cards = player.deck_cards[6:]
        player.deck_count = len(player.deck_cards)


def start_phase(state: GameState):
    active = state.get_active()
    for s in active.battle_area:
        if s.unit_id and s.status == "rested":
            s.status = "active"
        if s.unit_id:
            s.turns_on_field += 1
    if active.base.status == "rested":
        active.base.status = "active"
    active.resources_active += active.resources_rested
    active.resources_rested = 0
    state.phase = "start"
    state.step = None


def draw_phase(state: GameState):
    state.phase = "draw"
    player = state.get_active()
    if len(player.deck_cards) == 0:
        state.game_over = True
        state.winner = state.get_opponent(state.active_player).player_id
        state.battle_log.append(f"{state.winner} wins by deck-out [CR-8.2]")
        return
    card = player.deck_cards.pop(0)
    player.hand_cards.append(card)
    player.deck_count = len(player.deck_cards)
    state.battle_log.append(f"{state.active_player} draws a card")
    if state.turn == 1 and state.active_player == state.first_player:
        player.hand_cards.append(card)


def resource_phase(state: GameState):
    state.phase = "resource"
    player = state.get_active()
    if player.resource_deck_count > 0:
        player.resource_deck_count -= 1
        player.resources_active += 1
        state.battle_log.append(f"{state.active_player} deploys a resource")


def can_play_card(state: GameState, player_id: str, card_id: str) -> Tuple[bool, str]:
    player = state.get_player(player_id)
    if card_id not in player.hand_cards:
        return False, "card not in hand"
    card_type = get_card_type(card_id)
    level = get_card_level(card_id)
    cost = get_card_cost(card_id)
    if card_type == "token":
        return False, "token cannot be played from hand"
    if player.level < level:
        return False, f"insufficient Level: need {level}, have {player.level}"
    if player.resources_active < cost:
        ex_needed = cost - player.resources_active
        if player.resources_ex < ex_needed:
            return False, f"insufficient resources: need {cost}, have {player.resources_active} active + {player.resources_ex} EX"
    return True, ""


def play_card(state: GameState, player_id: str, card_id: str, slot_idx: Optional[int] = None) -> Tuple[bool, str]:
    ok, reason = can_play_card(state, player_id, card_id)
    if not ok:
        return False, reason

    player = state.get_player(player_id)
    cost = get_card_cost(card_id)
    card_type = get_card_type(card_id)

    player.hand_cards.remove(card_id)

    if cost > 0:
        pay_cost(player, cost)

    if card_type in ("unit", "pilot"):
        if slot_idx is not None and 0 <= slot_idx < 6:
            slot = player.battle_area[slot_idx]
            if slot.unit_id is not None:
                player.trash.append(slot.unit_id)
            if card_type == "pilot" and slot.unit_id:
                slot.pilot_id = card_id
                ap = get_card_ap(card_id)
                slot.ap += ap
                kw = get_card_keywords(card_id)
                slot.keywords.extend(kw)
            else:
                slot.unit_id = card_id
                slot.ap = get_card_ap(card_id)
                slot.hp = get_card_hp(card_id)
                slot.damage = 0
                slot.status = "active"
                slot.keywords = get_card_keywords(card_id)
                slot.turns_on_field = 0
                unit_card = get_card(card_id)
                if unit_card:
                    link_names = unit_card.get("link", [])
                    if card_type == "pilot":
                        pass
                    elif slot.pilot_id:
                        pilot_card = get_card(slot.pilot_id)
                        if pilot_card:
                            pilot_name = pilot_card.get("name", "")
                            if pilot_name in link_names:
                                slot.link = True
                                slot.keywords.append("Link")
    elif card_type == "base":
        old_base_id = player.base.card_id
        if old_base_id != "EX-BASE":
            player.trash.append(old_base_id)
        player.base.card_id = card_id
        player.base.ap = get_card_ap(card_id)
        player.base.hp = get_card_hp(card_id)
        player.base.damage = 0
        player.base.alive = True
        player.base.status = "active"
        if player.shields > 0:
            reclaimed = player.deck_cards.pop(0) if player.deck_cards else None
            if reclaimed:
                player.hand_cards.append(reclaimed)
            player.shields -= 1
    elif card_type == "command":
        player.trash.append(card_id)

    state.battle_log.append(f"{player_id} plays/deploys {card_id}")
    return True, ""


def pay_cost(player: PlayerState, cost: int):
    for _ in range(cost):
        if player.resources_active > 0:
            player.resources_active -= 1
            player.resources_rested += 1
        elif player.resources_ex > 0:
            player.resources_ex -= 1


def can_attack(state: GameState, player_id: str, slot_idx: int) -> Tuple[bool, str]:
    if state.phase not in ("main",):
        return False, "can only attack in main phase"
    player = state.get_player(player_id)
    if slot_idx < 0 or slot_idx >= 6:
        return False, "invalid slot"
    slot = player.battle_area[slot_idx]
    if slot.unit_id is None:
        return False, "no unit in that slot"
    if slot.status == "rested":
        return False, "unit is rested"
    if not slot.link and slot.turns_on_field < 1:
        return False, "unit cannot attack this turn (summoning sickness)"
    if slot.ap <= 0:
        return False, "unit has 0 AP"
    return True, ""


def declare_attack(state: GameState, player_id: str, slot_idx: int) -> Tuple[bool, str]:
    ok, reason = can_attack(state, player_id, slot_idx)
    if not ok:
        return False, reason
    state.phase = "battle"
    state.step = "attack"
    state.current_attacker = slot_idx
    state.priority = player_id
    state.battle_log.append(f"{player_id} attacks with slot {slot_idx}")
    return True, ""


def can_block(state: GameState, defender_id: str, slot_idx: int) -> Tuple[bool, str]:
    if state.phase != "battle" or state.step not in ("attack", "block"):
        return False, "can only block during attack step"
    defender = state.get_player(defender_id)
    slot = defender.battle_area[slot_idx]
    if slot.unit_id is None:
        return False, "no unit in that slot"
    if slot.status == "rested":
        return False, "unit is rested"
    if "Blocker" not in slot.keywords:
        return False, "unit is not a Blocker"
    return True, ""


def resolve_block(state: GameState, blocker_slot: int):
    att_player = state.get_active()
    def_player = state.get_opponent(state.active_player)
    att_slot = att_player.battle_area[state.current_attacker]
    blk_slot = def_player.battle_area[blocker_slot]
    blk_slot.status = "rested"
    att_slot.status = "rested"

    if "First Strike" in att_slot.keywords:
        blk_slot.damage += att_slot.ap
        if blk_slot.damage >= blk_slot.hp:
            def_player.trash.append(blk_slot.unit_id)
            blk_slot.unit_id = None
            blk_slot.pilot_id = None
            blk_slot.ap = 0
            blk_slot.hp = 0
            blk_slot.damage = 0
            blk_slot.keywords = []
            blk_slot.link = False
            state.battle_log.append(f"Blocker slot {blocker_slot} destroyed by First Strike")
        else:
            att_slot.damage += blk_slot.ap
            if att_slot.damage >= att_slot.hp:
                att_player.trash.append(att_slot.unit_id)
                att_slot.unit_id = None
                att_slot.pilot_id = None
                att_slot.ap = 0
                att_slot.hp = 0
                att_slot.damage = 0
                att_slot.keywords = []
                att_slot.link = False
                state.battle_log.append(f"Attacker slot {state.current_attacker} destroyed in block")
    else:
        att_slot.damage += blk_slot.ap
        blk_slot.damage += att_slot.ap

        if att_slot.damage >= att_slot.hp:
            att_player.trash.append(att_slot.unit_id)
            att_slot.unit_id = None
            att_slot.pilot_id = None
            att_slot.ap = 0
            att_slot.hp = 0
            att_slot.damage = 0
            att_slot.keywords = []
            att_slot.link = False
            state.battle_log.append(f"Attacker slot {state.current_attacker} destroyed")

        if blk_slot.damage >= blk_slot.hp:
            def_player.trash.append(blk_slot.unit_id)
            blk_slot.unit_id = None
            blk_slot.pilot_id = None
            blk_slot.ap = 0
            blk_slot.hp = 0
            blk_slot.damage = 0
            blk_slot.keywords = []
            blk_slot.link = False
            state.battle_log.append(f"Blocker slot {blocker_slot} destroyed")

    state.step = "action"
    state.priority = def_player.player_id


def resolve_unblocked_attack(state: GameState):
    att_player = state.get_active()
    def_player = state.get_opponent(state.active_player)
    att_slot = att_player.battle_area[state.current_attacker]
    att_slot.status = "rested"
    damage = att_slot.ap

    if def_player.shields > 0 or def_player.base.alive:
        if def_player.base.alive:
            def_player.base.damage += damage
            state.battle_log.append(f"{att_slot.unit_id} deals {damage} damage to {def_player.player_id}'s Base")
            if def_player.base.damage >= def_player.base.hp:
                def_player.base.alive = False
                def_player.base.status = None
                state.battle_log.append(f"{def_player.player_id}'s Base destroyed")
        elif def_player.shields > 0:
            def_player.shields -= 1
            destroyed_shield = def_player.shield_cards.pop(0) if def_player.shield_cards else "unknown"
            def_player.trash.append(destroyed_shield)
            state.battle_log.append(f"{att_slot.unit_id} destroys {def_player.player_id}'s shield")
    else:
        state.game_over = True
        state.winner = att_player.player_id
        state.battle_log.append(f"{att_player.player_id} wins by direct hit [CR-4.9]")

    if "Breach" in [k for k in att_slot.keywords if k.startswith("Breach") or k == "Breach"]:
        breach_dmg = 1
        if def_player.base.alive:
            def_player.base.damage += breach_dmg
            state.battle_log.append(f"Breach: {breach_dmg} additional damage to Base")
            if def_player.base.damage >= def_player.base.hp:
                def_player.base.alive = False
                def_player.base.status = None
        elif def_player.shields > 0:
            def_player.shields -= 1
            destroyed_shield = def_player.shield_cards.pop(0) if def_player.shield_cards else "unknown"
            def_player.trash.append(destroyed_shield)
            state.battle_log.append(f"Breach: destroys {def_player.player_id}'s shield")

    state.step = "battle_end"
    state.current_attacker = None


def end_battle(state: GameState):
    state.phase = "main"
    state.step = None
    state.current_attacker = None
    state.priority = state.active_player


def pass_turn(state: GameState, player_id: str):
    if state.phase == "main":
        state.phase = "end"
        state.step = "action"
        opponent = state.get_opponent(state.active_player)
        state.priority = opponent.player_id
        state.battle_log.append(f"{player_id} ends turn")
    elif state.phase == "end" and state.step == "action":
        if player_id == state.priority:
            other = state.get_opponent(player_id).player_id
            if state.priority == state.active_player:
                cleanup_turn(state)
            else:
                state.priority = state.active_player
    elif state.phase == "battle" and state.step == "action":
        if player_id == state.priority:
            end_battle(state)


def cleanup_turn(state: GameState):
    active = state.get_active()
    if len(active.hand_cards) >= 11:
        pass
    state.step = "cleanup"
    opp = state.get_opponent(state.active_player)
    state.active_player = opp.player_id
    state.turn += 1
    state.phase = "start"
    state.step = None
    state.battle_log.append(f"Turn {state.turn} begins — {state.active_player}'s turn")
    start_phase(state)
    draw_phase(state)
    resource_phase(state)
    state.phase = "main"
    state.priority = state.active_player


def determine_winner(state: GameState) -> Optional[str]:
    if state.game_over:
        return state.winner

    for pid in ["P1", "P2"]:
        player = state.get_player(pid)
        if player.shields <= 0 and not player.base.alive:
            opp = state.get_opponent(pid)
            state.game_over = True
            state.winner = opp.player_id
            return opp.player_id

    if len(state.p1.deck_cards) == 0:
        state.game_over = True
        state.winner = "P2"
        return "P2"
    if len(state.p2.deck_cards) == 0:
        state.game_over = True
        state.winner = "P1"
        return "P1"

    return None


def get_phase_display(phase: str, step: Optional[str]) -> str:
    if phase == "pre-game":
        return "pre-game"
    if step:
        return f"{phase}({step})"
    return phase
