"""Lightweight rollout simulation for MCTS.

This is not the game engine. It is a small approximation used only on
synthetic belief states.
"""

from __future__ import annotations

import random

from ... import config
from ...engine.command_parser import CommandParser, parse_attack_target_ref, parse_slot_ref
from .determinization import UNKNOWN_CARD


class SimulationEngine:
    def __init__(self, card_database, rules_index, rng=None):
        self.cards = card_database
        self.rules = rules_index
        self.rng = rng or random.Random()
        self.parser = CommandParser()

    def legal_actions(self, state, player_id):
        if state.get("game_over"):
            return []
        if state.get("priority_player") != player_id:
            return []
        phase = state.get("phase")
        step = state.get("step")
        if phase == "main":
            return self._main_actions(state, player_id)
        if phase == "battle" and step == "block":
            return self._block_actions(state, player_id)
        if (phase == "battle" and step == "action") or (phase == "end" and step == "action"):
            return self._action_step_actions(state, player_id)
        return []

    def apply_action(self, state, player_id, command):
        before = _state_fingerprint(state)
        parsed = self.parser.parse(f"COMMAND: {command}", player_id)
        if parsed.command_type == "pass":
            self._apply_pass(state, player_id)
        elif parsed.command_type == "play_card":
            self._apply_play_card(state, player_id, parsed)
        elif parsed.command_type == "pair":
            self._apply_pair(state, player_id, parsed)
        elif parsed.command_type == "attack":
            self._apply_attack(state, player_id, parsed)
        elif parsed.command_type == "block":
            self._apply_block(state, player_id, parsed)
        elif parsed.command_type == "activate_effect":
            self._apply_activate_effect(state, player_id)
        elif parsed.command_type == "choose":
            pass
        self.advance_until_decision(state)
        return _state_fingerprint(state) != before

    def advance_until_decision(self, state):
        for _ in range(32):
            if state.get("game_over") or self._needs_decision(state):
                return
            if not self._advance_phase(state):
                return

    # ------------------------------------------------------------------
    # legal actions
    # ------------------------------------------------------------------

    def _main_actions(self, state, player_id):
        actions = []
        actions.extend(self._attack_actions(state, player_id))
        actions.extend(self._play_unit_actions(state, player_id))
        actions.extend(self._pair_actions(state, player_id))
        actions.extend(self._base_actions(state, player_id))
        actions.extend(self._command_actions(state, player_id, "MAIN"))
        if self._can_activate_base(state, player_id):
            actions.append("activate_effect base")
        actions.append("pass")
        return _dedupe(actions)

    def _block_actions(self, state, player_id):
        actions = []
        for slot in self._units(state, player_id):
            if slot.get("temp_cannot_attack") or slot.get("cont_cannot_attack"):
                continue
            if slot.get("status") == "active" and self._has_keyword(slot, "Blocker"):
                actions.append(f"block my_slot_{slot['slot']}")
        actions.append("pass")
        return actions

    def _action_step_actions(self, state, player_id):
        actions = self._command_actions(state, player_id, "ACTION")
        actions.append("pass")
        return _dedupe(actions)

    def _attack_actions(self, state, player_id):
        opponent = other_player(player_id)
        actions = []
        for slot in self._units(state, player_id):
            slot_index = slot["slot"]
            if not self._can_attack_with_unit(slot):
                continue
            if self._can_attack_player(slot):
                actions.append(f"attack my_slot_{slot_index} opponent_base")
            for enemy in self._units(state, opponent):
                if self._can_attack_unit_target(enemy):
                    actions.append(f"attack my_slot_{slot_index} opponent_slot_{enemy['slot']}")
        return actions

    def _play_unit_actions(self, state, player_id):
        empty_slots = self._empty_slots(state, player_id)
        if not empty_slots:
            return []
        actions = []
        slot = empty_slots[0]
        for card_id, card in self._hand_cards(state, player_id):
            if card.get("cardType") != "unit" or not self._affordable(state, player_id, card):
                continue
            actions.append(f"play_card {card_id} {slot}")
        return actions

    def _pair_actions(self, state, player_id):
        pairable = [slot["slot"] for slot in self._units(state, player_id) if slot.get("pilot_id") is None]
        if not pairable:
            return []
        actions = []
        for card_id, card in self._hand_cards(state, player_id):
            if card.get("cardType") != "pilot" and self.rules.pilot_designation(card_id) is None:
                continue
            if not self._affordable(state, player_id, card):
                continue
            for slot in pairable:
                actions.append(f"pair {card_id} my_slot_{slot}")
        return actions

    def _base_actions(self, state, player_id):
        if self._base_alive(state, player_id):
            return []
        actions = []
        for card_id, card in self._hand_cards(state, player_id):
            if card.get("cardType") == "base" and self._affordable(state, player_id, card):
                actions.append(f"play_card {card_id}")
        return actions

    def _command_actions(self, state, player_id, timing):
        actions = []
        for card_id, card in self._hand_cards(state, player_id):
            if card.get("cardType") != "command" or not self._affordable(state, player_id, card):
                continue
            if timing in self.rules.play_windows(card_id):
                actions.append(f"play_card {card_id}")
        return actions

    # ------------------------------------------------------------------
    # action application
    # ------------------------------------------------------------------

    def _apply_pass(self, state, player_id):
        phase = state.get("phase")
        step = state.get("step")
        if phase == "main":
            state["phase"] = "end"
            state["step"] = "action"
            self._start_action_window(state, "end", other_player(state["active_player"]))
            return
        if phase == "battle" and step == "block":
            self._enter_battle_action(state, player_id)
            return
        if (phase == "battle" and step == "action") or (phase == "end" and step == "action"):
            window = state.setdefault("action_window", {})
            last = window.get("last_action_player")
            window["consecutive_passes"] = window.get("consecutive_passes", 0) + 1 if last != player_id else 1
            window["last_action_player"] = player_id
            if window["consecutive_passes"] >= 2:
                state["priority_player"] = None
                state["action_window"] = _empty_action_window()
                if phase == "battle":
                    state["step"] = "damage"
                else:
                    state["step"] = "end_step"
                return
            state["priority_player"] = other_player(player_id)

    def _apply_play_card(self, state, player_id, parsed):
        card_id = parsed.source_ref
        card = self.cards.get(card_id)
        if card is None or card_id not in state["players"][player_id]["hand"]:
            return
        card_type = card.get("cardType")
        self._pay_cost(state, player_id, card)
        state["players"][player_id]["hand"].remove(card_id)
        if card_type == "unit" and parsed.args:
            self._deploy_unit(state, player_id, card_id, int(parsed.args[0]))
        elif card_type == "base":
            self._deploy_base(state, player_id, card_id)
        elif card_type == "command":
            self._apply_light_command(state, player_id, card)
            state["players"][player_id]["trash"].append(card_id)
        self._record_action(state, player_id)

    def _apply_pair(self, state, player_id, parsed):
        card_id = parsed.source_ref
        card = self.cards.get(card_id)
        slot = self._slot(state, player_id, parse_slot_ref(parsed.target_ref))
        if card is None or slot.get("unit_id") is None or slot.get("pilot_id") is not None:
            return
        if card_id not in state["players"][player_id]["hand"]:
            return
        self._pay_cost(state, player_id, card)
        state["players"][player_id]["hand"].remove(card_id)
        designation = self.rules.pilot_designation(card_id)
        pilot_name = card.get("name") if card.get("cardType") == "pilot" else (designation or {}).get("name")
        ap_bonus = int(card.get("ap") or 0) if card.get("cardType") == "pilot" else int((designation or {}).get("ap") or 0)
        hp_bonus = int(card.get("hp") or 0) if card.get("cardType") == "pilot" else int((designation or {}).get("hp") or 0)
        slot["pilot_id"] = card_id
        slot["pilot_name"] = pilot_name
        slot["ap"] = int(slot.get("ap") or 0) + ap_bonus
        slot["hp"] = int(slot.get("hp") or 0) + hp_bonus
        unit = self.cards.get(slot.get("unit_id")) or {}
        slot["is_link"] = pilot_name in (unit.get("link") or [])
        self._record_action(state, player_id)

    def _apply_attack(self, state, player_id, parsed):
        attacker_slot = parse_slot_ref(parsed.source_ref)
        attacker = self._slot(state, player_id, attacker_slot)
        if not self._can_attack_with_unit(attacker):
            return
        target_kind, target_slot = parse_attack_target_ref(parsed.target_ref or "opponent_base")
        if target_kind == "base" and not self._can_attack_player(attacker):
            return
        if target_kind == "unit":
            target = self._slot(state, other_player(player_id), target_slot)
            if not target or not self._can_attack_unit_target(target):
                return
        attacker["status"] = "rested"
        state["battle_context"] = {
            "attacker_player": player_id,
            "attacker_slot": attacker_slot,
            "defender_player": other_player(player_id),
            "target_kind": target_kind,
            "target_slot": target_slot,
            "blocker_slot": None,
        }
        state["phase"] = "battle"
        state["step"] = "attack"
        state["priority_player"] = None

    def _apply_block(self, state, player_id, parsed):
        blocker_slot = parse_slot_ref(parsed.source_ref)
        blocker = self._slot(state, player_id, blocker_slot)
        if blocker.get("status") != "active" or not self._has_keyword(blocker, "Blocker"):
            return
        blocker["status"] = "rested"
        context = state.get("battle_context") or {}
        context["blocker_slot"] = blocker_slot
        state["battle_context"] = context
        self._enter_battle_action(state, player_id)

    def _apply_activate_effect(self, state, player_id):
        # Mirrors the current runtime/action enumerator, which only supports
        # ``activate_effect base``. Unit activated abilities need an explicit
        # rollout model if the runtime adds them later.
        base = state["players"][player_id].get("base") or {}
        if base.get("status") == "active":
            base["status"] = "rested"
            self._deploy_best_token(state, player_id)
            self._record_action(state, player_id)

    # ------------------------------------------------------------------
    # phase machine
    # ------------------------------------------------------------------

    def _advance_phase(self, state):
        phase = state.get("phase")
        step = state.get("step")
        active = state.get("active_player") or "P1"
        if phase == "start":
            self._ready_player(state, active)
            self._increment_turns(state, active)
            state["phase"] = "draw"
            return True
        if phase == "draw":
            if not self._draw_one(state, active):
                self._mark_winner(state, other_player(active), "deck_out")
            else:
                state["phase"] = "resource"
            return True
        if phase == "resource":
            self._deploy_resource(state, active)
            state["phase"] = "main"
            state["step"] = None
            state["priority_player"] = active
            return True
        if phase == "battle" and step == "attack":
            defender = other_player(active)
            attacker = self._current_attacker(state)
            block_actions = self._block_actions(state, defender)
            if (
                attacker
                and not self._has_keyword(attacker, "High-Maneuver")
                and any(action.startswith("block ") for action in block_actions)
            ):
                state["step"] = "block"
                state["priority_player"] = defender
            else:
                self._enter_battle_action(state, defender)
            return True
        if phase == "battle" and step == "damage":
            self._apply_battle_damage(state)
            if not state.get("game_over"):
                state["step"] = "battle_end"
            return True
        if phase == "battle" and step == "battle_end":
            state["battle_context"] = None
            state["action_window"] = _empty_action_window()
            state["phase"] = "main"
            state["step"] = None
            state["priority_player"] = active
            return True
        if phase == "end" and step == "end_step":
            state["step"] = "hand"
            return True
        if phase == "end" and step == "hand":
            self._discard_to_hand_limit(state, active)
            state["step"] = "cleanup"
            return True
        if phase == "end" and step == "cleanup":
            next_player = other_player(active)
            self._clear_temporary(state)
            state["active_player"] = next_player
            state["priority_player"] = None
            state["turn"] = int(state.get("turn") or 0) + 1
            state["phase"] = "start"
            state["step"] = None
            return True
        if phase in {"pre-game", None}:
            state["active_player"] = active
            state["phase"] = "start"
            state["step"] = None
            return True
        return False

    def _needs_decision(self, state):
        return bool(self.legal_actions(state, state.get("priority_player")))

    # ------------------------------------------------------------------
    # battle
    # ------------------------------------------------------------------

    def _apply_battle_damage(self, state):
        context = state.get("battle_context") or {}
        attacker_player = context.get("attacker_player")
        defender_player = context.get("defender_player")
        attacker = self._slot(state, attacker_player, context.get("attacker_slot"))
        if not attacker or attacker.get("unit_id") is None:
            return
        target_slot = context.get("blocker_slot")
        if target_slot is None and context.get("target_kind") == "unit":
            target_slot = context.get("target_slot")
        if target_slot is None:
            self._deal_defense_damage(state, defender_player, int(attacker.get("ap") or 0), attacker_player)
            return
        defender = self._slot(state, defender_player, target_slot)
        if not defender or defender.get("unit_id") is None:
            return
        attacker_first = self._has_keyword(attacker, "First Strike")
        defender_first = self._has_keyword(defender, "First Strike")
        if attacker_first and not defender_first:
            self._damage_unit(state, defender_player, target_slot, int(attacker.get("ap") or 0))
            if self._unit_alive(defender):
                self._damage_unit(state, attacker_player, attacker["slot"], int(defender.get("ap") or 0))
        elif defender_first and not attacker_first:
            self._damage_unit(state, attacker_player, attacker["slot"], int(defender.get("ap") or 0))
            if self._unit_alive(attacker):
                self._damage_unit(state, defender_player, target_slot, int(attacker.get("ap") or 0))
        else:
            self._damage_unit(state, defender_player, target_slot, int(attacker.get("ap") or 0))
            self._damage_unit(state, attacker_player, attacker["slot"], int(defender.get("ap") or 0))
        defender_destroyed = not self._unit_alive(defender)
        self._destroy_dead_units(state)
        if defender_destroyed:
            breach = self._breach_value(attacker)
            self._deal_shield_damage(state, defender_player, breach, attacker_player)

    # ------------------------------------------------------------------
    # state helpers
    # ------------------------------------------------------------------

    def _hand_cards(self, state, player_id):
        seen = set()
        for card_id in state["players"][player_id]["hand"]:
            if card_id in seen or card_id == UNKNOWN_CARD:
                continue
            seen.add(card_id)
            card = self.cards.get(card_id)
            if card is not None:
                yield card_id, card

    def _affordable(self, state, player_id, card):
        resources = state["players"][player_id]["resources"]
        level = int(resources.get("active") or 0) + int(resources.get("rested") or 0) + int(resources.get("ex") or 0)
        spendable = int(resources.get("active") or 0) + int(resources.get("ex") or 0)
        return level >= int(card.get("level") or 0) and spendable >= int(card.get("cost") or 0)

    def _pay_cost(self, state, player_id, card):
        cost = int(card.get("cost") or 0)
        resources = state["players"][player_id]["resources"]
        spend_active = min(int(resources.get("active") or 0), cost)
        resources["active"] = int(resources.get("active") or 0) - spend_active
        resources["rested"] = int(resources.get("rested") or 0) + spend_active
        remaining = cost - spend_active
        if remaining > 0:
            resources["ex"] = max(0, int(resources.get("ex") or 0) - remaining)

    def _deploy_unit(self, state, player_id, card_id, slot_index):
        slot = self._slot(state, player_id, slot_index)
        card = self.cards.get(card_id) or {}
        if slot.get("unit_id") is not None:
            return
        slot.update({
            "unit_id": card_id,
            "pilot_id": None,
            "pilot_name": None,
            "ap": int(card.get("ap") or 0),
            "hp": int(card.get("hp") or 0),
            "damage": 0,
            "status": "active",
            "keywords": self.rules.keywords(card_id),
            "is_link": False,
            "turns_on_field": 0,
        })

    def _deploy_base(self, state, player_id, card_id):
        card = self.cards.get(card_id) or {}
        state["players"][player_id]["base"] = {
            "card_id": card_id,
            "ap": int(card.get("ap") or 0),
            "hp": int(card.get("hp") or 0),
            "damage": 0,
            "alive": True,
            "status": "active",
        }

    def _apply_light_command(self, state, player_id, card):
        action = self._classify_command(card)
        if action == "draw":
            self._draw_one(state, player_id)
        elif action == "destroy":
            self._destroy_best_enemy(state, player_id)
        elif action == "rest":
            target = self._best_enemy_unit(state, player_id)
            if target:
                target["status"] = "rested"
        elif action == "buff":
            target = self._best_own_unit(state, player_id)
            if target:
                target["ap"] = int(target.get("ap") or 0) + 1
                target["hp"] = int(target.get("hp") or 0) + 1
        elif action == "heal":
            # Rollout approximation: current command classification does not
            # model per-card repair values, so healing uses the ST01 value.
            target = self._most_damaged_own_unit(state, player_id)
            if target:
                target["damage"] = max(0, int(target.get("damage") or 0) - 3)
        elif action == "resource":
            state["players"][player_id]["resources"]["active"] = int(state["players"][player_id]["resources"].get("active") or 0) + 1

    def _classify_command(self, card):
        # CardDatabase preserves the structured card JSON ``effects.rules``.
        # The rollout intentionally does not infer effects from prose text.
        effects = card.get("effects") or {}
        rules = effects.get("rules") or []
        if not isinstance(rules, list):
            return None
        actions = {rule.get("action") for rule in rules if isinstance(rule, dict)}
        if {"draw", "draw_then_discard"} & actions:
            return "draw"
        if {"destroy", "damage"} & actions:
            return "destroy"
        if "rest" in actions:
            return "rest"
        if {"modifyAP", "modifyHP", "grantKeyword"} & actions:
            return "buff"
        if "heal" in actions:
            return "heal"
        resource_actions = {"resource", "addresource", "gainresource", "deployresource"}
        if {str(action).replace("_", "").lower() for action in actions} & resource_actions:
            return "resource"
        return None

    def _record_action(self, state, player_id):
        window = state.setdefault("action_window", _empty_action_window())
        window["consecutive_passes"] = 0
        window["last_action_player"] = player_id

    def _start_action_window(self, state, origin, priority_player):
        state["action_window"] = {
            "active": True,
            "origin": origin,
            "consecutive_passes": 0,
            "last_action_player": None,
        }
        state["priority_player"] = priority_player

    def _enter_battle_action(self, state, priority_player):
        state["step"] = "action"
        self._start_action_window(state, "battle", priority_player)

    def _ready_player(self, state, player_id):
        player = state["players"][player_id]
        resources = player["resources"]
        resources["active"] = int(resources.get("active") or 0) + int(resources.get("rested") or 0)
        resources["rested"] = 0
        for slot in player["battle_area"]:
            if slot.get("unit_id") is not None:
                slot["status"] = "active"
        base = player.get("base")
        if base and base.get("alive", True):
            base["status"] = "active"

    def _increment_turns(self, state, player_id):
        for slot in self._units(state, player_id):
            slot["turns_on_field"] = int(slot.get("turns_on_field") or 0) + 1

    def _draw_one(self, state, player_id):
        deck = state["players"][player_id]["deck"]
        if not deck:
            return None
        card_id = deck.pop(0)
        if card_id != UNKNOWN_CARD:
            state["players"][player_id]["hand"].append(card_id)
        else:
            state["players"][player_id]["hand"].append(UNKNOWN_CARD)
        return card_id

    def _deploy_resource(self, state, player_id):
        player = state["players"][player_id]
        if int(player.get("resource_deck_count") or 0) <= 0:
            return False
        player["resource_deck_count"] = int(player.get("resource_deck_count") or 0) - 1
        player["resources"]["active"] = int(player["resources"].get("active") or 0) + 1
        return True

    def _clear_temporary(self, state):
        state["action_window"] = _empty_action_window()
        state["battle_context"] = None

    def _discard_to_hand_limit(self, state, player_id):
        player = state["players"][player_id]
        while len(player.get("hand") or []) > config.HAND_LIMIT:
            card_id = player["hand"].pop()
            if card_id != UNKNOWN_CARD:
                player["trash"].append(card_id)

    def _deal_defense_damage(self, state, player_id, damage, source_player):
        if damage <= 0:
            return
        player = state["players"][player_id]
        base = player.get("base")
        if base and base.get("alive", True):
            base["damage"] = int(base.get("damage") or 0) + damage
            if base["damage"] >= int(base.get("hp") or 0):
                base["alive"] = False
                if base.get("card_id") and base.get("card_id") != "EX-BASE":
                    player["trash"].append(base["card_id"])
            return
        self._deal_shield_damage(state, player_id, damage, source_player)

    def _deal_shield_damage(self, state, player_id, damage, source_player):
        if damage <= 0:
            return
        player = state["players"][player_id]
        if player["shield"]:
            player["shield"].pop(0)
        else:
            self._mark_winner(state, source_player, "player_damage")

    def _damage_unit(self, state, player_id, slot_index, damage):
        slot = self._slot(state, player_id, slot_index)
        slot["damage"] = int(slot.get("damage") or 0) + max(0, damage)

    def _destroy_dead_units(self, state):
        for player_id in ("P1", "P2"):
            for slot in state["players"][player_id]["battle_area"]:
                if slot.get("unit_id") is not None and not self._unit_alive(slot):
                    if slot.get("unit_id") != UNKNOWN_CARD:
                        state["players"][player_id]["trash"].append(slot["unit_id"])
                    if slot.get("pilot_id"):
                        state["players"][player_id]["trash"].append(slot["pilot_id"])
                    slot.update(_empty_slot(slot["slot"]))

    def _destroy_best_enemy(self, state, player_id):
        target = self._best_enemy_unit(state, player_id)
        if target:
            target["damage"] = int(target.get("hp") or 0)
            self._destroy_dead_units(state)

    def _deploy_best_token(self, state, player_id):
        empty = self._empty_slots(state, player_id)
        if not empty:
            return
        unit_count = len(list(self._units(state, player_id)))
        if unit_count == 0:
            ap, hp = 3, 3
        elif unit_count == 1:
            ap, hp = 2, 2
        else:
            ap, hp = 1, 1
        slot = self._slot(state, player_id, empty[0])
        slot.update({
            "unit_id": "TOKEN",
            "pilot_id": None,
            "ap": ap,
            "hp": hp,
            "damage": 0,
            "status": "active",
            "keywords": [],
            "is_link": False,
            "turns_on_field": 0,
        })

    def _mark_winner(self, state, winner, reason):
        state["game_over"] = True
        state["winner"] = winner
        state["win_reason"] = reason
        state["priority_player"] = None

    def _can_activate_base(self, state, player_id):
        base = state["players"][player_id].get("base")
        return bool(
            base
            and base.get("alive", True)
            and base.get("status") == "active"
            and base.get("card_id") != "EX-BASE"
            and self.rules.has_activated_main(base.get("card_id"))
        )

    def _base_alive(self, state, player_id):
        base = state["players"][player_id].get("base")
        return bool(base and base.get("alive", True))

    def _current_attacker(self, state):
        context = state.get("battle_context") or {}
        if not context:
            return None
        return self._slot(state, context.get("attacker_player"), context.get("attacker_slot"))

    def _can_attack_with_unit(self, slot):
        if not slot or slot.get("unit_id") is None or slot.get("status") != "active":
            return False
        if slot.get("temp_cannot_attack") or slot.get("cont_cannot_attack"):
            return False
        return int(slot.get("turns_on_field") or 0) >= 1 or bool(slot.get("is_link"))

    def _can_attack_player(self, slot):
        return (
            self.rules.can_attack_player(slot.get("unit_id"))
            and not slot.get("temp_cannot_attack_player")
            and not slot.get("cont_cannot_attack_player")
        )

    def _can_attack_unit_target(self, target):
        return target.get("unit_id") is not None and target.get("status") == "rested"

    def _unit_alive(self, slot):
        return slot.get("unit_id") is not None and int(slot.get("damage") or 0) < int(slot.get("hp") or 0)

    def _has_keyword(self, slot, keyword):
        keywords = slot.get("keywords") or []
        return keyword in keywords or any(str(item).startswith(f"{keyword}:") for item in keywords)

    def _breach_value(self, slot):
        for keyword in slot.get("keywords") or []:
            if str(keyword).startswith("Breach:"):
                return int(str(keyword).split(":", 1)[1] or 0)
        return 0

    def _best_enemy_unit(self, state, player_id):
        units = list(self._units(state, other_player(player_id)))
        return max(units, key=lambda slot: (int(slot.get("ap") or 0), int(slot.get("hp") or 0)), default=None)

    def _best_own_unit(self, state, player_id):
        units = list(self._units(state, player_id))
        return max(units, key=lambda slot: (int(slot.get("ap") or 0), int(slot.get("hp") or 0)), default=None)

    def _most_damaged_own_unit(self, state, player_id):
        units = [slot for slot in self._units(state, player_id) if int(slot.get("damage") or 0) > 0]
        return max(units, key=lambda slot: int(slot.get("damage") or 0), default=None)

    def _units(self, state, player_id):
        for slot in state["players"][player_id]["battle_area"]:
            if slot.get("unit_id") is not None:
                yield slot

    def _empty_slots(self, state, player_id):
        return [slot["slot"] for slot in state["players"][player_id]["battle_area"] if slot.get("unit_id") is None]

    def _slot(self, state, player_id, slot_index):
        if player_id is None or slot_index is None:
            return None
        for slot in state["players"][player_id]["battle_area"]:
            if slot["slot"] == int(slot_index):
                return slot
        return None


def other_player(player_id):
    return "P2" if player_id == "P1" else "P1"


def _empty_action_window():
    return {
        "active": False,
        "origin": None,
        "consecutive_passes": 0,
        "last_action_player": None,
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
        "is_link": False,
        "turns_on_field": 0,
    }


def _state_fingerprint(state):
    players = []
    for player_id in ("P1", "P2"):
        player = state.get("players", {}).get(player_id, {})
        battle_area = tuple(
            (
                slot.get("slot"),
                slot.get("unit_id"),
                slot.get("pilot_id"),
                int(slot.get("ap") or 0),
                int(slot.get("hp") or 0),
                int(slot.get("damage") or 0),
                slot.get("status"),
                tuple(slot.get("keywords") or []),
                bool(slot.get("is_link")),
                int(slot.get("turns_on_field") or 0),
            )
            for slot in player.get("battle_area", [])
        )
        base = player.get("base") or {}
        players.append((
            player_id,
            tuple(player.get("hand") or []),
            len(player.get("deck") or []),
            tuple(player.get("shield") or []),
            tuple(sorted((player.get("resources") or {}).items())),
            int(player.get("resource_deck_count") or 0),
            (
                base.get("card_id"),
                int(base.get("ap") or 0),
                int(base.get("hp") or 0),
                int(base.get("damage") or 0),
                bool(base.get("alive", True)),
                base.get("status"),
            ),
            battle_area,
            tuple(player.get("trash") or []),
        ))
    return (
        state.get("phase"),
        state.get("step"),
        state.get("active_player"),
        state.get("priority_player"),
        int(state.get("turn") or 0),
        bool(state.get("game_over")),
        state.get("winner"),
        state.get("win_reason"),
        repr(state.get("battle_context")),
        repr(state.get("action_window")),
        tuple(players),
    )


def _dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
