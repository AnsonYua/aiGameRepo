"""In-memory owner of the real game state.

唯一 state mutator 的資料層：

- 只持有 state 與低階變更 API
- 不做策略、不解讀卡牌文字、不自行驗證規則
- gameState.yaml 只是 snapshot，不是 source of truth
"""

from __future__ import annotations

import random
from copy import deepcopy
from datetime import datetime

from .. import config


class StateStore:
    def __init__(self, card_database, deck_config, snapshot_writer=None):
        self.card_database = card_database
        self.deck_config = deck_config
        self.snapshot_writer = snapshot_writer
        self.game_id = None
        self.state = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def create_game_shell(self, p1_deck_id="deck001", p2_deck_id="deck001"):
        self.game_id = self._build_game_id()
        p1_deck = self.deck_config.get_deck(p1_deck_id)
        p2_deck = self.deck_config.get_deck(p2_deck_id)
        self.state = {
            "game_id": self.game_id,
            "turn": 0,
            "phase": "pre-game",
            "step": "opening",
            "active_player": None,
            "priority_player": None,
            "action_window": self._empty_action_window(),
            "battle_context": None,
            "pending_choice": [],
            "trigger_queue": [],
            "once_per_turn_used": [],
            "game_over": False,
            "winner": None,
            "win_reason": None,
            "opening": {
                "decision_player": None,
                "first_player": None,
                "second_player": None,
                "mulligan_done": {"P1": False, "P2": False},
            },
            "players": {
                "P1": self._build_player_state("P1", p1_deck),
                "P2": self._build_player_state("P2", p2_deck),
            },
        }
        self.save_snapshot()
        return self.game_id

    def mark_game_over(self, winner, reason=None):
        self.state["game_over"] = True
        self.state["winner"] = winner
        self.state["win_reason"] = reason

    # ------------------------------------------------------------------
    # basic getters / setters
    # ------------------------------------------------------------------

    def get_game_id(self):
        return self.game_id

    def get_state(self):
        return self.state

    def get_player_state(self, player_id):
        return self.state["players"][player_id]

    def get_other_player(self, player_id):
        return "P2" if player_id == "P1" else "P1"

    def get_priority_player(self):
        return self.state["priority_player"]

    def set_priority_player(self, player_id):
        self.state["priority_player"] = player_id

    def get_active_player(self):
        return self.state["active_player"]

    def set_active_player(self, player_id):
        self.state["active_player"] = player_id

    def get_turn(self):
        return self.state["turn"]

    def set_turn(self, turn):
        self.state["turn"] = turn

    def get_phase(self):
        return self.state["phase"]

    def set_phase(self, phase):
        self.state["phase"] = phase

    def get_step(self):
        return self.state["step"]

    def set_step(self, step):
        self.state["step"] = step

    # ------------------------------------------------------------------
    # opening / mulligan
    # ------------------------------------------------------------------

    def choose_random_player(self):
        return random.choice(["P1", "P2"])

    def set_decision_player(self, player_id):
        self.state["opening"]["decision_player"] = player_id

    def set_first_player(self, player_id):
        self.state["opening"]["first_player"] = player_id

    def set_second_player(self, player_id):
        self.state["opening"]["second_player"] = player_id

    def get_first_player(self):
        return self.state["opening"]["first_player"]

    def get_second_player(self):
        return self.state["opening"]["second_player"]

    def shuffle_main_deck(self, player_id):
        random.shuffle(self.state["players"][player_id]["deck"])

    def draw_cards(self, player_id, count):
        player = self.state["players"][player_id]
        draw_count = min(count, len(player["deck"]))
        drawn = player["deck"][:draw_count]
        player["hand"].extend(drawn)
        del player["deck"][:draw_count]
        return drawn

    def draw_one_card(self, player_id):
        drawn = self.draw_cards(player_id, 1)
        return drawn[0] if drawn else None

    def return_hand_to_deck_for_mulligan(self, player_id):
        player = self.state["players"][player_id]
        player["deck"].extend(player["hand"])
        player["hand"] = []
        self.shuffle_main_deck(player_id)

    def mark_mulligan_done(self, player_id):
        self.state["opening"]["mulligan_done"][player_id] = True

    def is_mulligan_done(self, player_id):
        return self.state["opening"]["mulligan_done"][player_id]

    def place_shields(self, player_id, count):
        player = self.state["players"][player_id]
        shield_count = min(count, len(player["deck"]))
        player["shield"].extend(player["deck"][:shield_count])
        del player["deck"][:shield_count]

    def deploy_ex_base(self, player_id):
        self.state["players"][player_id]["base"] = {
            "card_id": "EX-BASE",
            "ap": 0,
            "hp": 3,
            "damage": 0,
            "alive": True,
            "status": "active",
        }

    def set_ex_resource(self, player_id, amount):
        self.state["players"][player_id]["resources"]["ex"] = min(amount, config.EX_RESOURCE_CAP)

    # ------------------------------------------------------------------
    # priority / action window
    # ------------------------------------------------------------------

    def start_action_window(self, origin, priority_player):
        self.state["action_window"] = {
            "active": True,
            "origin": origin,
            "consecutive_passes": 0,
            "last_action_player": None,
        }
        self.state["priority_player"] = priority_player

    def clear_action_window(self):
        self.state["action_window"] = self._empty_action_window()

    def get_action_window(self):
        return self.state.get("action_window", {})

    def record_priority_pass(self, player_id):
        window = self.state.setdefault("action_window", self._empty_action_window())
        last_player = window.get("last_action_player")
        if last_player is not None and last_player != player_id:
            window["consecutive_passes"] = window.get("consecutive_passes", 0) + 1
        else:
            window["consecutive_passes"] = 1
        window["last_action_player"] = player_id
        return window["consecutive_passes"]

    def record_priority_action(self, player_id):
        window = self.state.setdefault("action_window", self._empty_action_window())
        window["consecutive_passes"] = 0
        window["last_action_player"] = player_id

    def needs_action_window(self):
        if self.state["game_over"]:
            return False
        if self.state["pending_choice"] or self.state["trigger_queue"]:
            return False
        phase = self.state["phase"]
        step = self.state["step"]
        return (
            phase == "main"
            or (phase == "battle" and step in {"block", "action"})
            or (phase == "end" and step == "action")
        )

    # ------------------------------------------------------------------
    # battle context
    # ------------------------------------------------------------------

    def set_battle_context(self, battle_context):
        self.state["battle_context"] = battle_context

    def get_battle_context(self):
        return self.state.get("battle_context")

    def clear_battle_context(self):
        self.state["battle_context"] = None

    # ------------------------------------------------------------------
    # pending choices / triggers
    # ------------------------------------------------------------------

    def peek_pending_choice(self):
        if not self.state["pending_choice"]:
            return None
        return self.state["pending_choice"][0]

    def list_pending_choices(self):
        return list(self.state["pending_choice"])

    def enqueue_pending_choice(self, choice):
        self.state["pending_choice"].append(choice)

    def push_pending_choice_front(self, choice):
        self.state["pending_choice"].insert(0, choice)

    def pop_pending_choice(self):
        if self.state["pending_choice"]:
            return self.state["pending_choice"].pop(0)
        return None

    def enqueue_trigger(self, trigger_event):
        self.state["trigger_queue"].append(trigger_event)

    def pop_next_trigger(self):
        return self.state["trigger_queue"].pop(0)

    def has_trigger(self):
        return len(self.state["trigger_queue"]) > 0

    # ------------------------------------------------------------------
    # once per turn tracking
    # ------------------------------------------------------------------

    def once_per_turn_key(self, player_id, source_ref, effect_key):
        return f"{player_id}:{source_ref}:{effect_key}"

    def is_once_per_turn_used(self, key):
        return key in self.state["once_per_turn_used"]

    def mark_once_per_turn_used(self, key):
        if key not in self.state["once_per_turn_used"]:
            self.state["once_per_turn_used"].append(key)

    def clear_once_per_turn(self):
        self.state["once_per_turn_used"] = []

    # ------------------------------------------------------------------
    # resources / level / cost
    # ------------------------------------------------------------------

    def total_level(self, player_id):
        resources = self.state["players"][player_id]["resources"]
        return resources["active"] + resources["rested"] + resources["ex"]

    def available_cost_resources(self, player_id):
        resources = self.state["players"][player_id]["resources"]
        return resources["active"] + resources["ex"]

    def pay_cost(self, player_id, cost):
        resources = self.state["players"][player_id]["resources"]
        if resources["active"] + resources["ex"] < cost:
            raise ValueError("not enough spendable resources")
        spend_active = min(resources["active"], cost)
        resources["active"] -= spend_active
        resources["rested"] += spend_active
        remaining = cost - spend_active
        if remaining > 0:
            resources["ex"] -= remaining

    def deploy_resource_from_deck(self, player_id):
        player = self.state["players"][player_id]
        if player["resource_deck_count"] <= 0:
            return False
        player["resource_deck_count"] -= 1
        player["resources"]["active"] += 1
        return True

    def set_one_resource_active(self, player_id):
        """將 1 個 rested 資源轉為 active（資源同質，毋須選擇）。"""
        resources = self.state["players"][player_id]["resources"]
        if resources["rested"] <= 0:
            return False
        resources["rested"] -= 1
        resources["active"] += 1
        return True

    # ------------------------------------------------------------------
    # hand / trash
    # ------------------------------------------------------------------

    def discard_from_hand(self, player_id, card_id):
        player = self.state["players"][player_id]
        if card_id not in player["hand"]:
            raise ValueError(f"card '{card_id}' is not in {player_id} hand")
        player["hand"].remove(card_id)
        player["trash"].append(card_id)

    def remove_from_hand(self, player_id, card_id):
        player = self.state["players"][player_id]
        if card_id not in player["hand"]:
            raise ValueError(f"card '{card_id}' is not in {player_id} hand")
        player["hand"].remove(card_id)

    def add_to_trash(self, player_id, card_id):
        self.state["players"][player_id]["trash"].append(card_id)

    def add_to_hand(self, player_id, card_id):
        self.state["players"][player_id]["hand"].append(card_id)

    def take_shield_to_hand(self, player_id):
        """將自己最上面 1 面盾牌加入手牌，回傳 card_id 或 None。"""
        player = self.state["players"][player_id]
        if not player["shield"]:
            return None
        card_id = player["shield"].pop(0)
        player["hand"].append(card_id)
        return card_id

    # ------------------------------------------------------------------
    # battle area
    # ------------------------------------------------------------------

    def find_empty_slots(self, player_id):
        return [
            slot["slot"]
            for slot in self.state["players"][player_id]["battle_area"]
            if slot["unit_id"] is None
        ]

    def get_slot(self, player_id, slot_index):
        for slot in self.state["players"][player_id]["battle_area"]:
            if slot["slot"] == slot_index:
                return slot
        raise ValueError(f"unknown slot: {slot_index}")

    def iter_units(self, player_id):
        for slot in self.state["players"][player_id]["battle_area"]:
            if slot["unit_id"] is not None:
                yield slot

    def deploy_unit_from_hand(self, player_id, card_id, slot_index, keywords=None):
        player = self.state["players"][player_id]
        if card_id not in player["hand"]:
            raise ValueError(f"{card_id} is not in {player_id} hand")
        self._place_unit(player_id, card_id, slot_index, keywords=keywords)
        player["hand"].remove(card_id)

    def deploy_token(self, player_id, token_card_id, slot_index, keywords=None):
        self._place_unit(player_id, token_card_id, slot_index, keywords=keywords, is_token=True)

    def _place_unit(self, player_id, card_id, slot_index, keywords=None, is_token=False):
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is not None:
            raise ValueError(f"slot {slot_index} is not empty")
        card = self.card_database.get(card_id)
        if card is None:
            raise ValueError(f"unknown card: {card_id}")
        slot.update({
            "unit_id": card_id,
            "pilot_id": None,
            "pilot_name": None,
            "base_ap": int(card.get("ap") or 0),
            "base_hp": int(card.get("hp") or 0),
            "pilot_ap": 0,
            "pilot_hp": 0,
            "temp_ap_mod": 0,
            "cont_ap_mod": 0,
            "damage": 0,
            "status": "active",
            "keywords": list(keywords or []),
            "link_names": list(card.get("link") or []),
            "is_link": False,
            "is_token": is_token,
            "turns_on_field": 0,
        })
        self.recompute_slot_stats(slot)

    def pair_pilot(self, player_id, slot_index, pilot_card_id, pilot_name, ap_bonus, hp_bonus):
        player = self.state["players"][player_id]
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            raise ValueError(f"slot {slot_index} has no unit")
        if slot["pilot_id"] is not None:
            raise ValueError(f"slot {slot_index} already has a pilot")
        if pilot_card_id not in player["hand"]:
            raise ValueError(f"{pilot_card_id} is not in {player_id} hand")
        player["hand"].remove(pilot_card_id)
        slot["pilot_id"] = pilot_card_id
        slot["pilot_name"] = pilot_name
        slot["pilot_ap"] = int(ap_bonus or 0)
        slot["pilot_hp"] = int(hp_bonus or 0)
        slot["is_link"] = pilot_name in (slot.get("link_names") or [])
        self.recompute_slot_stats(slot)
        return slot

    def recompute_slot_stats(self, slot):
        if slot.get("unit_id") is None:
            return
        slot["ap"] = max(
            0,
            slot.get("base_ap", 0)
            + slot.get("pilot_ap", 0)
            + slot.get("temp_ap_mod", 0)
            + slot.get("cont_ap_mod", 0),
        )
        slot["hp"] = max(0, slot.get("base_hp", 0) + slot.get("pilot_hp", 0))

    def set_continuous_ap_mod(self, player_id, slot_index, amount):
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            return
        slot["cont_ap_mod"] = amount
        self.recompute_slot_stats(slot)

    def rest_unit(self, player_id, slot_index):
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            raise ValueError(f"slot {slot_index} has no unit")
        slot["status"] = "rested"

    def set_unit_active(self, player_id, slot_index):
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            raise ValueError(f"slot {slot_index} has no unit")
        slot["status"] = "active"

    def unit_alive(self, slot):
        return slot.get("unit_id") is not None and slot.get("damage", 0) < slot.get("hp", 0)

    def can_attack_with_unit(self, player_id, slot_index):
        slot = self.get_slot(player_id, slot_index)
        if not self.unit_alive(slot) or slot.get("status") != "active":
            return False
        if slot.get("turns_on_field", 0) >= 1:
            return True
        # Link Unit 可在部署當回合攻擊
        return bool(slot.get("is_link"))

    def can_block_with_unit(self, player_id, slot_index):
        slot = self.get_slot(player_id, slot_index)
        return (
            self.unit_alive(slot)
            and slot.get("status") == "active"
            and "Blocker" in (slot.get("keywords") or [])
        )

    def deal_damage_to_unit(self, player_id, slot_index, damage):
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            raise ValueError(f"slot {slot_index} has no unit")
        slot["damage"] += max(0, damage)
        return slot["damage"] >= slot["hp"]

    def heal_unit(self, player_id, slot_index, amount):
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            return 0
        before = slot["damage"]
        slot["damage"] = max(0, slot["damage"] - max(0, amount))
        return before - slot["damage"]

    def modify_unit_ap_until_end_of_turn(self, player_id, slot_index, amount):
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            return
        slot["temp_ap_mod"] = slot.get("temp_ap_mod", 0) + amount
        self.recompute_slot_stats(slot)

    def modify_unit_hp(self, player_id, slot_index, amount):
        """永久 HP 修正（V2 暫不支援回合結束回復的 HP buff）。"""
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            return
        slot["base_hp"] = max(0, slot.get("base_hp", 0) + amount)
        self.recompute_slot_stats(slot)

    def destroy_unit(self, player_id, slot_index):
        """強制移除 Unit（含 pilot）進廢棄區，回傳 (unit_id, pilot_id)。"""
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            return None, None
        unit_id = slot["unit_id"]
        pilot_id = slot.get("pilot_id")
        trash = self.state["players"][player_id]["trash"]
        if not slot.get("is_token"):
            trash.append(unit_id)
        if pilot_id is not None:
            trash.append(pilot_id)
        slot.update(self._build_empty_slot(slot["slot"]))
        return unit_id, pilot_id

    def destroy_unit_if_lethal(self, player_id, slot_index):
        slot = self.get_slot(player_id, slot_index)
        if slot["unit_id"] is None:
            return None
        if slot["damage"] < slot["hp"]:
            return None
        unit_id, _pilot_id = self.destroy_unit(player_id, slot_index)
        return unit_id

    # ------------------------------------------------------------------
    # base / defense
    # ------------------------------------------------------------------

    def get_base(self, player_id):
        return self.state["players"][player_id].get("base")

    def base_alive(self, player_id):
        base = self.get_base(player_id)
        return bool(base and base.get("alive", True))

    def deploy_base(self, player_id, card_id, ap, hp):
        if self.base_alive(player_id):
            raise ValueError("base section is occupied")
        self.state["players"][player_id]["base"] = {
            "card_id": card_id,
            "ap": int(ap or 0),
            "hp": int(hp or 0),
            "damage": 0,
            "alive": True,
            "status": "active",
        }

    def rest_base(self, player_id):
        base = self.get_base(player_id)
        if not base or not base.get("alive", True):
            raise ValueError("no base to rest")
        if base.get("status") == "rested":
            raise ValueError("base is already rested")
        base["status"] = "rested"

    def deal_damage_to_defense(self, player_id, damage):
        """Base → 盾牌 → 玩家 的防禦層傷害。0 傷害不發生任何事。

        回傳 dict：target ∈ {none, base, shield, player}；shield 時附 card_id。
        """
        if damage <= 0:
            return {"target": "none", "destroyed": False}
        player = self.state["players"][player_id]
        base = player.get("base")
        if base and base.get("alive", True):
            base["damage"] += damage
            if base["damage"] >= base["hp"]:
                base["alive"] = False
                if base.get("card_id") and base["card_id"] != "EX-BASE":
                    player["trash"].append(base["card_id"])
                return {"target": "base", "destroyed": True}
            return {"target": "base", "destroyed": False}
        if player["shield"]:
            card_id = player["shield"].pop(0)
            return {"target": "shield", "destroyed": True, "card_id": card_id}
        return {"target": "player", "destroyed": True}

    # ------------------------------------------------------------------
    # turn upkeep
    # ------------------------------------------------------------------

    def ready_units_and_base(self, player_id):
        player = self.state["players"][player_id]
        resources = player["resources"]
        resources["active"] += resources["rested"]
        resources["rested"] = 0
        for slot in player["battle_area"]:
            if slot["unit_id"] is not None:
                slot["status"] = "active"
        base = player.get("base")
        if base is not None and base.get("alive", True):
            base["status"] = "active"

    def increment_turns_on_field(self, player_id):
        for slot in self.state["players"][player_id]["battle_area"]:
            if slot["unit_id"] is not None:
                slot["turns_on_field"] = slot.get("turns_on_field", 0) + 1

    def clear_temporary_modifiers(self):
        for player in self.state["players"].values():
            for slot in player["battle_area"]:
                if slot.get("unit_id") is None:
                    continue
                slot["temp_ap_mod"] = 0
                self.recompute_slot_stats(slot)

    # ------------------------------------------------------------------
    # snapshot
    # ------------------------------------------------------------------

    def save_snapshot(self):
        if self.snapshot_writer is None:
            return
        self.snapshot_writer.write_game_state(game_id=self.game_id, snapshot=self.build_snapshot())

    def build_snapshot(self):
        """Public-safe snapshot（隱藏手牌/牌庫/盾牌內容，只留張數）。"""
        snapshot = {
            "game_id": self.state["game_id"],
            "turn": self.state["turn"],
            "phase": self.state["phase"],
            "step": self.state["step"],
            "active_player": self.state["active_player"],
            "priority_player": self.state["priority_player"],
            "action_window": deepcopy(self.state.get("action_window", {})),
            "battle_context": deepcopy(self.state.get("battle_context")),
            "pending_choice": [
                self._sanitize_pending_choice(choice)
                for choice in self.list_pending_choices()
            ],
            "game_over": self.state["game_over"],
            "winner": self.state["winner"],
            "win_reason": self.state.get("win_reason"),
            "p1": self._build_public_player_snapshot("P1"),
            "p2": self._build_public_player_snapshot("P2"),
        }
        if "opening" in self.state:
            snapshot["opening"] = {
                "decision_player": self.state["opening"]["decision_player"],
                "first_player": self.state["opening"]["first_player"],
                "second_player": self.state["opening"]["second_player"],
                "mulligan_done": dict(self.state["opening"]["mulligan_done"]),
            }
        return snapshot

    def build_gameplay_snapshot(self):
        """gamePlay.yaml 專用 snapshot：在 public snapshot 上補雙方手牌明細。

        只供 review/debug 的 gameplay log 使用；不可餵給 AI prompt 或 viewer。
        """
        snapshot = self.build_snapshot()
        for player_id, key in (("P1", "p1"), ("P2", "p2")):
            snapshot[key]["hand"] = list(self.state["players"][player_id]["hand"])
        return snapshot

    def _build_public_player_snapshot(self, player_id):
        player = self.state["players"][player_id]
        slots = deepcopy(player["battle_area"])
        return {
            "hand_count": len(player["hand"]),
            "deck_count": len(player["deck"]),
            "resource_deck_count": player["resource_deck_count"],
            "shields": len(player["shield"]),
            "resources": deepcopy(player["resources"]),
            "base": deepcopy(player["base"]),
            "board": {
                "units": sum(1 for slot in slots if slot["unit_id"] is not None),
                "empty_slots": sum(1 for slot in slots if slot["unit_id"] is None),
                "rested_units": sum(1 for slot in slots if slot["status"] == "rested"),
                "damaged_units": sum(1 for slot in slots if slot["damage"] > 0),
                "blockers": sum(1 for slot in slots if "Blocker" in slot["keywords"]),
                "slots": slots,
            },
            "trash": list(player["trash"]),
            "removal": list(player["removal"]),
        }

    def _sanitize_pending_choice(self, choice):
        if not isinstance(choice, dict):
            return choice
        sanitized = {
            "type": choice.get("type"),
            "player_id": choice.get("player_id"),
            "message": choice.get("message"),
        }
        options = choice.get("options", [])
        if choice.get("hidden_options"):
            sanitized["options"] = [{"id": "hidden", "label": "hidden"} for _ in options]
        else:
            sanitized["options"] = deepcopy(options)
        return sanitized

    # ------------------------------------------------------------------
    # builders
    # ------------------------------------------------------------------

    def _build_player_state(self, player_id, deck_bundle):
        return {
            "player_id": player_id,
            "deck": list(deck_bundle["main_deck"]),
            "hand": [],
            "shield": [],
            "resource_deck_count": deck_bundle["resource_deck_size"],
            "tokens": list(deck_bundle.get("tokens") or []),
            "resources": {"active": 0, "rested": 0, "ex": 0},
            "base": None,
            "battle_area": [
                self._build_empty_slot(slot) for slot in range(config.BATTLE_AREA_SLOTS)
            ],
            "trash": [],
            "removal": [],
        }

    def _empty_action_window(self):
        return {
            "active": False,
            "origin": None,
            "consecutive_passes": 0,
            "last_action_player": None,
        }

    def _build_empty_slot(self, slot):
        return {
            "slot": slot,
            "unit_id": None,
            "pilot_id": None,
            "pilot_name": None,
            "base_ap": 0,
            "base_hp": 0,
            "pilot_ap": 0,
            "pilot_hp": 0,
            "temp_ap_mod": 0,
            "cont_ap_mod": 0,
            "ap": 0,
            "hp": 0,
            "damage": 0,
            "status": None,
            "keywords": [],
            "link_names": [],
            "is_link": False,
            "is_token": False,
            "turns_on_field": 0,
        }

    def _build_game_id(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"game_{timestamp}"
