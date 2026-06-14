"""Legal command enumeration.

為當前決策點枚舉合法 COMMAND 清單：

- AI player 從這份清單逐字選 1 條（decision problem 與 legality 徹底分離）
- 枚舉使用與 runtime 相同的 state/rules 判定
- Command 卡是否可用需要 effect spec（LLM 解讀，process 內快取）；
  解讀失敗的卡不會出現在清單中，並記 warning
"""

from __future__ import annotations

import logging

from .effect_engine import new_effect_run


logger = logging.getLogger(__name__)


class ActionEnumerator:
    def __init__(self, state_store, card_database, rules_index, effect_engine, interpreter):
        self.state = state_store
        self.cards = card_database
        self.rules_index = rules_index
        self.effect_engine = effect_engine
        self.interpreter = interpreter

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def legal_commands(self, player_id):
        phase = self.state.get_phase()
        step = self.state.get_step()
        if self.state.peek_pending_choice() is not None:
            return self.pending_choice_commands(self.state.peek_pending_choice())
        if self.state.get_priority_player() != player_id:
            return []
        if phase == "main":
            return self._main_phase_commands(player_id)
        if phase == "battle" and step == "block":
            return self._block_commands(player_id)
        if (phase == "battle" and step == "action") or (phase == "end" and step == "action"):
            return self._action_step_commands(player_id)
        return []

    def pending_choice_commands(self, pending_choice):
        return [f"choose {option['id']}" for option in pending_choice.get("options", [])]

    # ------------------------------------------------------------------
    # main phase
    # ------------------------------------------------------------------

    def _main_phase_commands(self, player_id):
        commands = []
        commands.extend(self._attack_commands(player_id))
        commands.extend(self._deploy_unit_commands(player_id))
        commands.extend(self._pair_commands(player_id))
        commands.extend(self._base_deploy_commands(player_id))
        commands.extend(self._command_card_commands(player_id, timing="MAIN"))
        commands.extend(self._activate_base_commands(player_id))
        commands.append("pass")
        return commands

    def _affordable(self, player_id, card):
        return (
            self.state.total_level(player_id) >= int(card.get("level") or 0)
            and self.state.available_cost_resources(player_id) >= int(card.get("cost") or 0)
        )

    def _hand_cards(self, player_id):
        seen = set()
        for card_id in self.state.get_player_state(player_id)["hand"]:
            if card_id in seen:
                continue
            seen.add(card_id)
            card = self.cards.get(card_id)
            if card is not None:
                yield card_id, card

    def _deploy_unit_commands(self, player_id):
        empty_slots = self.state.find_empty_slots(player_id)
        if not empty_slots:
            return []
        slot_index = empty_slots[0]
        commands = []
        for card_id, card in self._hand_cards(player_id):
            if card.get("cardType") != "unit":
                continue
            if not self._affordable(player_id, card):
                continue
            commands.append(f"play_card {card_id} {slot_index}")
        return commands

    def _pair_commands(self, player_id):
        pairable_slots = [
            slot["slot"]
            for slot in self.state.iter_units(player_id)
            if slot.get("pilot_id") is None
        ]
        if not pairable_slots:
            return []
        commands = []
        for card_id, card in self._hand_cards(player_id):
            is_pilot = card.get("cardType") == "pilot"
            is_designation = (
                card.get("cardType") == "command"
                and self.rules_index.pilot_designation(card_id) is not None
            )
            if not (is_pilot or is_designation):
                continue
            if not self._affordable(player_id, card):
                continue
            for slot_index in pairable_slots:
                commands.append(f"pair {card_id} my_slot_{slot_index}")
        return commands

    def _base_deploy_commands(self, player_id):
        if self.state.base_alive(player_id):
            return []
        commands = []
        for card_id, card in self._hand_cards(player_id):
            if card.get("cardType") != "base":
                continue
            if not self._affordable(player_id, card):
                continue
            commands.append(f"play_card {card_id}")
        return commands

    def _command_card_commands(self, player_id, timing):
        commands = []
        for card_id, card in self._hand_cards(player_id):
            if card.get("cardType") != "command":
                continue
            if timing not in self.rules_index.play_windows(card_id):
                continue
            if not self._affordable(player_id, card):
                continue
            spec = self._safe_interpret(card, timing, player_id, source_zone="hand")
            if spec is None or spec.get("status") == "unsupported":
                continue
            if not self._first_requirement_satisfiable(spec, player_id, card_id):
                continue
            commands.append(f"play_card {card_id}")
        return commands

    def _activate_base_commands(self, player_id):
        base = self.state.get_base(player_id)
        if not base or not base.get("alive", True) or base.get("card_id") == "EX-BASE":
            return []
        card_id = base["card_id"]
        if not self.rules_index.has_activated_main(card_id):
            return []
        card = self.cards.get(card_id)
        spec = self._safe_interpret(card, "ACTIVATE_MAIN", player_id, source_zone="base")
        if spec is None or spec.get("status") == "unsupported":
            return []
        cost = spec.get("cost") or {}
        if cost.get("rest_source") and base.get("status") == "rested":
            return []
        if self.state.available_cost_resources(player_id) < int(cost.get("resources") or 0):
            return []
        if spec.get("once_per_turn"):
            once_key = self.state.once_per_turn_key(player_id, "base", card_id)
            if self.state.is_once_per_turn_used(once_key):
                return []
        if not self._first_requirement_satisfiable(spec, player_id, card_id):
            return []
        return ["activate_effect base"]

    def _attack_commands(self, player_id):
        opponent = self.state.get_other_player(player_id)
        rested_enemy_slots = [
            slot["slot"]
            for slot in self.state.iter_units(opponent)
            if slot.get("status") == "rested" and self.state.unit_alive(slot)
        ]
        commands = []
        for slot in self.state.iter_units(player_id):
            slot_index = slot["slot"]
            if not self.state.can_attack_with_unit(player_id, slot_index):
                continue
            if self.rules_index.can_attack_player(slot["unit_id"]):
                commands.append(f"attack my_slot_{slot_index} opponent_base")
            for enemy_slot in rested_enemy_slots:
                commands.append(f"attack my_slot_{slot_index} opponent_slot_{enemy_slot}")
        return commands

    # ------------------------------------------------------------------
    # battle / action steps
    # ------------------------------------------------------------------

    def _block_commands(self, player_id):
        commands = []
        for slot in self.state.iter_units(player_id):
            if self.state.can_block_with_unit(player_id, slot["slot"]):
                commands.append(f"block my_slot_{slot['slot']}")
        commands.append("pass")
        return commands

    def _action_step_commands(self, player_id):
        commands = self._command_card_commands(player_id, timing="ACTION")
        commands.append("pass")
        return commands

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _safe_interpret(self, card, timing, player_id, source_zone):
        try:
            return self.interpreter.interpret(card, timing, {
                "game_id": self.state.get_game_id(),
                "controller": player_id,
                "source_zone": source_zone,
            })
        except Exception as exc:  # noqa: BLE001 - 枚舉時解讀失敗只跳過該卡
            logger.warning(
                "enumerator interpretation failed card=%s timing=%s error=%s",
                card.get("id"), timing, exc,
            )
            return None

    def _first_requirement_satisfiable(self, spec, player_id, card_id):
        requirements = spec.get("target_requirements") or []
        if not requirements:
            return True
        probe_run = new_effect_run(
            spec,
            controller=player_id,
            source_card_id=card_id,
        )
        options = self.effect_engine.enumerate_targets(requirements[0], probe_run)
        return bool(options)
