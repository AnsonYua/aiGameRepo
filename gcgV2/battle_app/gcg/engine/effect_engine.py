"""Deterministic effect engine.

收 gate 驗證過的 effect spec 後：

- ``enumerate_targets``：依 target_requirements 枚舉合法目標（Python 決定候選集）
- ``evaluate_condition``：條件真假由 Python 查 state 判定
- ``execute``：依 primitive_steps 逐步執行，回傳事件清單供 trigger 偵測與 logging

LLM 永遠不直接進到這層；它只產生 spec。
"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


class EffectExecutionError(ValueError):
    """效果執行失敗（effect execution problem）。"""


def new_effect_run(spec, controller, source_card_id, source_slot=None, source_zone="battle_area"):
    return {
        "spec": spec,
        "controller": controller,
        "source_card_id": source_card_id,
        "source_slot": source_slot,
        "source_zone": source_zone,
        "bindings": {},
        "requirement_index": 0,
        "source_consumed": False,
    }


class EffectEngine:
    def __init__(self, state_store, card_database, rules_index):
        self.state = state_store
        self.cards = card_database
        self.rules_index = rules_index

    # ------------------------------------------------------------------
    # targets
    # ------------------------------------------------------------------

    def next_unbound_requirement(self, run):
        requirements = run["spec"].get("target_requirements") or []
        index = run["requirement_index"]
        if index < len(requirements):
            return requirements[index]
        return None

    def enumerate_targets(self, requirement, run):
        """回傳 [{id, label, player, slot}]；id 以效果控制者視角命名。"""
        controller = run["controller"]
        opponent = self.state.get_other_player(controller)
        card_type = requirement.get("card_type")

        if card_type == "resource":
            # 資源同質：有 rested 資源即可，毋須列舉個體
            target_player = controller if requirement.get("controller") in {"self", None} else opponent
            resources = self.state.get_player_state(target_player)["resources"]
            if resources["rested"] > 0:
                return [{"id": "self_resource", "label": "1 個 rested 資源", "player": target_player, "slot": None}]
            return []

        if card_type == "shield":
            target_player = controller if requirement.get("controller") in {"self", None} else opponent
            shield_count = len(self.state.get_player_state(target_player).get("shield") or [])
            if shield_count > 0:
                return [{"id": "self_shield_top", "label": "最上面的盾牌", "player": target_player, "slot": None}]
            return []

        if card_type != "unit":
            return []

        sides = []
        requirement_controller = requirement.get("controller", "any")
        if requirement_controller in {"self", "any"}:
            sides.append((controller, "my_slot"))
        if requirement_controller in {"opponent", "any"}:
            sides.append((opponent, "opponent_slot"))

        options = []
        for player_id, prefix in sides:
            for slot in self.state.iter_units(player_id):
                if not self._matches_unit_filters(slot, requirement, run, player_id):
                    continue
                options.append({
                    "id": f"{prefix}_{slot['slot']}",
                    "label": f"{slot['unit_id']}（{prefix}_{slot['slot']}）",
                    "player": player_id,
                    "slot": slot["slot"],
                })
        return options

    def _matches_unit_filters(self, slot, requirement, run, player_id):
        if not self.state.unit_alive(slot):
            return False
        status = requirement.get("status")
        if status is not None and slot.get("status") != status:
            return False
        remaining_hp = slot.get("hp", 0) - slot.get("damage", 0)
        if "hp_lte" in requirement and remaining_hp > requirement["hp_lte"]:
            return False
        if "hp_gte" in requirement and remaining_hp < requirement["hp_gte"]:
            return False
        if "ap_lte" in requirement and slot.get("ap", 0) > requirement["ap_lte"]:
            return False
        if "ap_gte" in requirement and slot.get("ap", 0) < requirement["ap_gte"]:
            return False
        card = self.cards.get(slot.get("unit_id")) or {}
        level = int(card.get("level") or 0)
        if "level_lte" in requirement and level > requirement["level_lte"]:
            return False
        if "level_gte" in requirement and level < requirement["level_gte"]:
            return False
        if "damage_gte" in requirement and slot.get("damage", 0) < requirement["damage_gte"]:
            return False
        if requirement.get("damaged_only") and slot.get("damage", 0) <= 0:
            return False
        if requirement.get("link_required") and not slot.get("is_link"):
            return False
        if requirement.get("other_than_source"):
            if player_id == run["controller"] and slot.get("slot") == run.get("source_slot"):
                return False
        trait_any = requirement.get("trait_any")
        if trait_any:
            traits = set(card.get("traits") or [])
            if not traits.intersection(set(trait_any)):
                return False
        keyword_has = requirement.get("keyword_has")
        if keyword_has and keyword_has not in (slot.get("keywords") or []):
            return False
        return True

    def bind_target(self, run, option):
        requirement = self.next_unbound_requirement(run)
        if requirement is None:
            raise EffectExecutionError("no unbound target requirement")
        run["bindings"][requirement["name"]] = {
            "player": option["player"],
            "slot": option["slot"],
            "id": option["id"],
        }
        run["requirement_index"] += 1
        return run

    # ------------------------------------------------------------------
    # conditions
    # ------------------------------------------------------------------

    def evaluate_condition(self, condition, run):
        condition_type = condition.get("type")
        controller = run["controller"]
        if condition_type == "all_of":
            return all(self.evaluate_condition(child, run) for child in condition.get("conditions") or [])
        if condition_type == "not":
            return not self.evaluate_condition(condition.get("condition") or {}, run)
        if condition_type == "is_your_turn":
            return self.state.get_active_player() == controller
        if condition_type == "source_is_paired":
            slot = self._source_slot(run)
            return bool(slot and slot.get("pilot_id"))
        if condition_type == "pilot_trait_any":
            slot = self._source_slot(run)
            if not slot or not slot.get("pilot_id"):
                return False
            pilot_card = self.cards.get(slot["pilot_id"]) or {}
            traits = set(pilot_card.get("traits") or [])
            return bool(traits.intersection(set(condition.get("traits") or [])))
        if condition_type == "friendly_units_gte":
            count = sum(1 for _ in self.state.iter_units(controller))
            return count >= int(condition.get("count") or 0)
        if condition_type == "enemy_units_gte":
            opponent = self.state.get_other_player(controller)
            count = sum(1 for _ in self.state.iter_units(opponent))
            return count >= int(condition.get("count") or 0)
        if condition_type == "target_destroyed":
            binding = run["bindings"].get(str(condition.get("target", "")).lstrip("$"))
            if not binding or binding.get("slot") is None:
                return False
            slot = self.state.get_slot(binding["player"], binding["slot"])
            return slot.get("unit_id") is None
        if condition_type == "pilot_level":
            slot = self._source_slot(run)
            if not slot or not slot.get("pilot_id"):
                return False
            pilot = self.cards.get(slot["pilot_id"]) or {}
            return self._compare_int(int(pilot.get("level") or 0), condition.get("op"), condition.get("value"))
        if condition_type == "source_ap":
            slot = self._source_slot(run)
            return bool(slot and self._compare_int(int(slot.get("ap") or 0), condition.get("op"), condition.get("value")))
        if condition_type == "resonance_active":
            slot = self._source_slot(run)
            return bool(slot and slot.get("is_link"))
        if condition_type == "another_link_unit_exists":
            for slot in self.state.iter_units(controller):
                if slot.get("slot") == run.get("source_slot"):
                    continue
                if slot.get("is_link"):
                    return True
            return False
        if condition_type == "trash_card_name_contains":
            value = condition.get("value") or ""
            for card_id in self.state.get_player_state(controller)["trash"]:
                card = self.cards.get(card_id) or {}
                if value and value in (card.get("name") or ""):
                    return True
            return False
        if condition_type == "board_count":
            target_controller = condition.get("controller", "self")
            player_id = controller if target_controller == "self" else self.state.get_other_player(controller)
            count = 0
            for slot in self.state.iter_units(player_id):
                if condition.get("token") is not None and bool(slot.get("is_token")) != bool(condition.get("token")):
                    continue
                extra = condition.get("extra_filters") or {}
                trait_any = extra.get("trait_any")
                if trait_any:
                    card = self.cards.get(slot.get("unit_id")) or {}
                    traits = set(card.get("traits") or [])
                    if not traits.intersection(set(trait_any)):
                        continue
                count += 1
            return self._compare_int(count, condition.get("op"), condition.get("value"))
        raise EffectExecutionError(f"unsupported condition type: {condition_type}")

    def _compare_int(self, actual, op, expected):
        expected = int(expected or 0)
        if op == "gte":
            return actual >= expected
        if op == "lte":
            return actual <= expected
        if op == "eq":
            return actual == expected
        return False

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    def execute(self, run):
        """執行所有 primitive_steps，回傳 (events, messages)。"""
        if self.next_unbound_requirement(run) is not None:
            raise EffectExecutionError("effect run still has unbound targets")
        events = []
        messages = []
        for step in run["spec"].get("primitive_steps") or []:
            self._execute_step(step, run, events, messages)
            if self._game_over():
                break
        return events, messages

    def _game_over(self):
        return bool(self.state.get_state().get("game_over"))

    def _execute_step(self, step, run, events, messages):
        primitive = step.get("primitive")
        handler = getattr(self, f"_op_{primitive}", None)
        if handler is None:
            raise EffectExecutionError(f"unsupported primitive in executor: {primitive}")
        handler(step, run, events, messages)

    # --- wrappers ---

    def _op_sequence(self, step, run, events, messages):
        for child in step.get("steps") or []:
            self._execute_step(child, run, events, messages)
            if self._game_over():
                break

    def _op_conditional(self, step, run, events, messages):
        condition = step.get("condition") or {}
        if self.evaluate_condition(condition, run):
            for child in step.get("steps") or []:
                self._execute_step(child, run, events, messages)
                if self._game_over():
                    break
        else:
            for child in step.get("else_steps") or []:
                self._execute_step(child, run, events, messages)
                if self._game_over():
                    break

    # --- unit ops ---

    def _op_damage(self, step, run, events, messages):
        amount = int(step.get("amount") or 0)
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            slot = self.state.get_slot(player_id, slot_index)
            if slot["unit_id"] is None:
                continue
            unit_id = slot["unit_id"]
            self.state.deal_damage_to_unit(player_id, slot_index, amount)
            messages.append(f"對 {player_id} 的 {unit_id}（{slot_index} 號位）造成 {amount} 點傷害。")
            destroyed = self.state.destroy_unit_if_lethal(player_id, slot_index)
            if destroyed:
                events.append({
                    "type": "unit_destroyed",
                    "player": player_id,
                    "slot": slot_index,
                    "card_id": destroyed,
                })
                messages.append(f"{player_id} 的 {destroyed} 被擊破並進入廢棄區。")

    def _op_heal(self, step, run, events, messages):
        amount = int(step.get("amount") or 0)
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            healed = self.state.heal_unit(player_id, slot_index, amount)
            if healed > 0:
                slot = self.state.get_slot(player_id, slot_index)
                messages.append(
                    f"{player_id} 的 {slot['unit_id']}（{slot_index} 號位）恢復 {healed} 點 HP。"
                )

    def _op_rest(self, step, run, events, messages):
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            slot = self.state.get_slot(player_id, slot_index)
            if slot["unit_id"] is None:
                continue
            self.state.rest_unit(player_id, slot_index)
            events.append({"type": "unit_rested", "player": player_id, "slot": slot_index})
            messages.append(f"{player_id} 的 {slot['unit_id']}（{slot_index} 號位）被設為 rested。")

    def _op_setActive(self, step, run, events, messages):
        target = step.get("target")
        resource_player = self._resolve_resource_target_player(target, run)
        if resource_player is not None:
            if self.state.set_one_resource_active(resource_player):
                events.append({"type": "resource_activated", "player": resource_player})
                messages.append(f"{resource_player} 將 1 個資源設為 active。")
            return
        for player_id, slot_index in self._resolve_unit_targets(target, run):
            slot = self.state.get_slot(player_id, slot_index)
            if slot["unit_id"] is None:
                continue
            self.state.set_unit_active(player_id, slot_index)
            messages.append(f"{player_id} 的 {slot['unit_id']}（{slot_index} 號位）被設為 active。")

    def _op_modifyAP(self, step, run, events, messages):
        amount = int(step.get("amount") or 0)
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            slot = self.state.get_slot(player_id, slot_index)
            if slot["unit_id"] is None:
                continue
            self.state.modify_unit_ap_until_end_of_turn(player_id, slot_index, amount)
            sign = "+" if amount >= 0 else ""
            messages.append(
                f"{player_id} 的 {slot['unit_id']}（{slot_index} 號位）本回合 AP{sign}{amount}。"
            )

    def _op_modifyHP(self, step, run, events, messages):
        amount = int(step.get("amount") or 0)
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            self.state.modify_unit_hp(player_id, slot_index, amount)
            slot = self.state.get_slot(player_id, slot_index)
            if slot["unit_id"] is None:
                continue
            messages.append(f"{player_id} 的 {slot['unit_id']} HP 修正 {amount}。")
            if slot["damage"] >= slot["hp"]:
                destroyed = self.state.destroy_unit_if_lethal(player_id, slot_index)
                if destroyed:
                    events.append({
                        "type": "unit_destroyed",
                        "player": player_id,
                        "slot": slot_index,
                        "card_id": destroyed,
                    })

    def _op_grant_keyword(self, step, run, events, messages):
        keyword = step.get("keyword")
        if not keyword:
            raise EffectExecutionError("grant_keyword missing keyword")
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            self.state.add_temporary_keyword(player_id, slot_index, keyword)
            valued_keyword = self._valued_keyword(keyword, step.get("amount"))
            if valued_keyword:
                self.state.add_temporary_keyword(player_id, slot_index, valued_keyword)
            slot = self.state.get_slot(player_id, slot_index)
            display_keyword = valued_keyword or keyword
            messages.append(f"{player_id} 的 {slot['unit_id']}（{slot_index} 號位）本回合獲得 {display_keyword}。")

    def _valued_keyword(self, keyword, amount):
        if amount is None or keyword not in {"Breach", "Support", "Repair"}:
            return None
        return f"{keyword}:{int(amount or 0)}"

    def _op_restrict_attack(self, step, run, events, messages):
        restriction = {
            "cannot_attack": bool(step.get("cannot_attack")),
            "cannot_target_player": bool(step.get("cannot_target_player")),
        }
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            self.state.add_temporary_attack_restriction(player_id, slot_index, restriction)
            slot = self.state.get_slot(player_id, slot_index)
            messages.append(f"{player_id} 的 {slot['unit_id']}（{slot_index} 號位）受到攻擊限制。")

    def _op_grant_damage_prevention(self, step, run, events, messages):
        target = step.get("target")
        prevention = {
            "damage_type": step.get("damage_type"),
            "source_filter": step.get("source_filter") or {},
        }
        if isinstance(target, str) and target.startswith("$"):
            binding = run["bindings"].get(target[1:])
            if binding and binding.get("id") == "self_shield_top":
                self.state.add_temporary_shield_damage_prevention(binding["player"], prevention)
                messages.append(f"{binding['player']} 的盾牌本次戰鬥獲得傷害防止。")
                return
        for player_id, slot_index in self._resolve_unit_targets(target, run):
            self.state.add_temporary_damage_prevention(player_id, slot_index, prevention)
            slot = self.state.get_slot(player_id, slot_index)
            messages.append(f"{player_id} 的 {slot['unit_id']}（{slot_index} 號位）本次戰鬥獲得傷害防止。")

    def _op_allow_attack_target(self, step, run, events, messages):
        filter_spec = step.get("attack_target_filter") or {}
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            self.state.add_temporary_attack_permission(player_id, slot_index, filter_spec)
            slot = self.state.get_slot(player_id, slot_index)
            messages.append(f"{player_id} 的 {slot['unit_id']}（{slot_index} 號位）本回合可攻擊額外目標。")

    def _op_destroy(self, step, run, events, messages):
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            unit_id, _pilot = self.state.destroy_unit(player_id, slot_index)
            if unit_id:
                events.append({
                    "type": "unit_destroyed",
                    "player": player_id,
                    "slot": slot_index,
                    "card_id": unit_id,
                })
                messages.append(f"{player_id} 的 {unit_id} 被破壞並進入廢棄區。")

    # --- card / resource ops ---

    def _op_draw(self, step, run, events, messages):
        amount = int(step.get("amount") or 1)
        controller = run["controller"]
        for _ in range(amount):
            drawn = self.state.draw_one_card(controller)
            if drawn is None or not self.state.get_player_state(controller)["deck"]:
                loser = controller
                winner = self.state.get_other_player(loser)
                self.state.mark_game_over(winner=winner, reason="deck_out")
                events.append({"type": "game_over", "winner": winner, "reason": "deck_out"})
                messages.append(f"{loser} 因效果抽牌後牌庫為空，{winner} 獲勝。")
                return
        events.append({"type": "draw", "player": controller, "count": amount})
        messages.append(f"{controller} 抽 {amount} 張牌。")

    def _op_discard(self, step, run, events, messages):
        amount = int(step.get("amount") or 1)
        discarded = self.state.discard_cards_from_hand(run["controller"], amount)
        if discarded:
            events.append({"type": "discard", "player": run["controller"], "count": len(discarded)})
        messages.append(f"{run['controller']} 棄置 {len(discarded)} 張手牌。")

    def _op_addExtraEnergy(self, step, run, events, messages):
        amount = int(step.get("amount") or 1)
        self.state.add_ex_resource(run["controller"], amount)
        events.append({"type": "ex_energy_added", "player": run["controller"], "count": amount})
        messages.append(f"{run['controller']} 放置 {amount} 張 EX 能源。")

    def _op_scry_top_deck(self, step, run, events, messages):
        result = self.state.scry_top_deck(
            run["controller"],
            int(step.get("amount") or 0),
            keep=int(step.get("keep") or 1),
            remainder=step.get("remainder") or "bottom",
        )
        messages.append(f"{run['controller']} 確認牌庫頂 {len(result['kept']) + len(result['remainder'])} 張並調整順序。")

    def _op_select_from_top_deck(self, step, run, events, messages):
        selected = self.state.select_from_top_deck(
            run["controller"],
            int(step.get("amount") or 0),
            step.get("filter") or {},
            count=int(step.get("count") or 1),
            to=step.get("to") or "hand",
            remainder=step.get("remainder") or "bottom",
        )
        messages.append(f"{run['controller']} 從牌庫頂選擇 {len(selected)} 張卡。")

    def _op_deploy_token(self, step, run, events, messages):
        token_spec = step.get("token") or {}
        token_spec["source_card_id"] = run["source_card_id"]
        count = max(1, int(token_spec.get("count") or 1))
        for _ in range(count):
            self._deploy_token_spec(token_spec, run, events, messages)

    def _op_addToHand(self, step, run, events, messages):
        target = step.get("target")
        controller = run["controller"]
        if target == "source":
            self.state.add_to_hand(controller, run["source_card_id"])
            run["source_consumed"] = True
            events.append({"type": "card_to_hand", "player": controller, "card_id": run["source_card_id"]})
            messages.append(f"{controller} 將 {run['source_card_id']} 加入手牌。")
            return
        if target == "self_shield_top":
            card_id = self.state.take_shield_to_hand(controller)
            if card_id is not None:
                events.append({"type": "shield_to_hand", "player": controller})
                messages.append(f"{controller} 將 1 面盾牌加入手牌。")
            return
        # Safety: handle bound shield target from LLM interpretation
        if isinstance(target, str) and target.startswith("$"):
            binding = run["bindings"].get(target[1:])
            if binding and binding.get("id") == "self_shield_top":
                card_id = self.state.take_shield_to_hand(controller)
                if card_id is not None:
                    events.append({"type": "shield_to_hand", "player": controller})
                    messages.append(f"{controller} 將 1 面盾牌加入手牌。")
                return
        raise EffectExecutionError(f"addToHand unsupported target: {target}")

    def _op_returnToHand(self, step, run, events, messages):
        for player_id, slot_index in self._resolve_unit_targets(step.get("target"), run):
            slot = self.state.get_slot(player_id, slot_index)
            unit_id = slot.get("unit_id")
            if unit_id is None:
                continue
            pilot_id = slot.get("pilot_id")
            is_token = slot.get("is_token")
            slot.update(self.state._build_empty_slot(slot["slot"]))
            if not is_token:
                self.state.add_to_hand(player_id, unit_id)
            if pilot_id:
                self.state.add_to_hand(player_id, pilot_id)
            events.append({"type": "unit_returned", "player": player_id, "slot": slot_index, "card_id": unit_id})
            messages.append(f"{player_id} 的 {unit_id} 回到手牌。")

    def _op_deploy(self, step, run, events, messages):
        """部署效果來源卡（目前支援 Base 卡，例如 [Burst]Deploy this card）。"""
        if step.get("target") not in {None, "source"}:
            raise EffectExecutionError("deploy primitive only supports source target")
        controller = run["controller"]
        card = self.cards.get(run["source_card_id"]) or {}
        if card.get("cardType") == "base":
            replaced = self.state.trash_existing_base_for_replacement(controller)
            self.state.deploy_base(
                controller,
                run["source_card_id"],
                ap=card.get("ap"),
                hp=card.get("hp"),
            )
            run["source_consumed"] = True
            events.append({"type": "base_deployed", "player": controller, "card_id": run["source_card_id"]})
            replace_note = f"（將原本的 {replaced} 送入廢棄區）" if replaced else ""
            messages.append(f"{controller} 部署基地 {run['source_card_id']}{replace_note}。")
            return
        if card.get("cardType") == "unit":
            empty_slots = self.state.find_empty_slots(controller)
            if not empty_slots:
                events.append({
                    "type": "replacement_required",
                    "player": controller,
                    "run": run,
                    "deploy_kind": "source_unit",
                    "card_id": run["source_card_id"],
                })
                return
            slot_index = empty_slots[0]
            keywords = self.rules_index.keywords(run["source_card_id"])
            self.state.deploy_token(controller, run["source_card_id"], slot_index, keywords=keywords)
            run["source_consumed"] = True
            events.append({
                "type": "unit_deployed",
                "player": controller,
                "slot": slot_index,
                "card_id": run["source_card_id"],
                "from_effect": True,
            })
            messages.append(f"{controller} 將 {run['source_card_id']} 部署到 {slot_index} 號位。")
            return
        raise EffectExecutionError(f"deploy unsupported card type: {card.get('cardType')}")

    def _op_conditionalTokenDeploy(self, step, run, events, messages):
        controller = run["controller"]
        unit_count = sum(1 for _ in self.state.iter_units(controller))
        token_spec = self._pick_token_spec(step.get("tokens") or [], unit_count)
        if token_spec is None:
            messages.append(f"{controller} 沒有符合條件的 token 可部署。")
            return
        token_spec["source_card_id"] = run["source_card_id"]
        self._deploy_token_spec(token_spec, run, events, messages)

    def _deploy_token_spec(self, token_spec, run, events, messages):
        controller = run["controller"]
        empty_slots = self.state.find_empty_slots(controller)
        if not empty_slots:
            events.append({
                "type": "replacement_required",
                "player": controller,
                "run": run,
                "deploy_kind": "token",
                "token_spec": token_spec,
            })
            return
        token_card_id = self._resolve_token_card_id(controller, token_spec)
        if token_card_id is None:
            raise EffectExecutionError(f"cannot resolve token card for spec: {token_spec}")
        slot_index = empty_slots[0]
        keywords = self.rules_index.keywords(token_card_id)
        self.state.deploy_token(controller, token_card_id, slot_index, keywords=keywords)
        events.append({
            "type": "unit_deployed",
            "player": controller,
            "slot": slot_index,
            "card_id": token_card_id,
            "from_effect": True,
            "is_token": True,
        })
        messages.append(
            f"{controller} 部署 token {token_card_id}（{token_spec.get('name')}）到 {slot_index} 號位。"
        )
        if token_spec.get("rested"):
            self.state.rest_unit(controller, slot_index)

    def _op_activate_ability(self, step, run, events, messages):
        ability = step.get("ability", "main")
        events.append({
            "type": "activate_ability_requested",
            "player": run["controller"],
            "card_id": run["source_card_id"],
            "ability": ability,
        })
        messages.append(f"{run['source_card_id']} 發動其 [{ability.upper()}] 效果。")

    # ------------------------------------------------------------------
    # target resolution helpers
    # ------------------------------------------------------------------

    def _resolve_unit_targets(self, target, run):
        """回傳 [(player_id, slot_index)]。"""
        controller = run["controller"]
        opponent = self.state.get_other_player(controller)
        if target is None:
            raise EffectExecutionError("primitive step missing target")
        if isinstance(target, str) and target.startswith("$"):
            binding = run["bindings"].get(target[1:])
            if binding is None:
                raise EffectExecutionError(f"unbound target reference: {target}")
            if binding.get("slot") is None:
                raise EffectExecutionError(f"binding {target} is not a unit target")
            return [(binding["player"], binding["slot"])]
        if target == "source":
            slot = self._source_slot(run)
            if slot is None:
                return []
            return [(controller, slot["slot"])]
        if target == "self_all_unit":
            return [(controller, slot["slot"]) for slot in self.state.iter_units(controller)]
        if target == "opponent_all_unit":
            return [(opponent, slot["slot"]) for slot in self.state.iter_units(opponent)]
        if target == "self_all_link_unit":
            return [
                (controller, slot["slot"])
                for slot in self.state.iter_units(controller)
                if slot.get("is_link")
            ]
        if target.startswith("self_all_unit_"):
            return [
                (controller, slot["slot"])
                for slot in self.state.iter_units(controller)
                if self._matches_unit_target_alias(slot, target.removeprefix("self_all_unit_"))
            ]
        if target.startswith("opponent_all_unit_"):
            return [
                (opponent, slot["slot"])
                for slot in self.state.iter_units(opponent)
                if self._matches_unit_target_alias(slot, target.removeprefix("opponent_all_unit_"))
            ]
        raise EffectExecutionError(f"unsupported target ref: {target}")

    def _matches_unit_target_alias(self, slot, suffix):
        parts = suffix.split("_")
        if len(parts) % 3 != 0:
            return False
        card = self.cards.get(slot.get("unit_id")) or {}
        for index in range(0, len(parts), 3):
            field, op, raw_value = parts[index:index + 3]
            try:
                value = int(raw_value)
            except ValueError:
                return False
            if field == "level":
                actual = int(card.get("level") or 0)
            elif field == "ap":
                actual = int(slot.get("ap") or 0)
            elif field == "hp":
                actual = int(slot.get("hp") or 0) - int(slot.get("damage") or 0)
            else:
                return False
            if op == "lte" and actual > value:
                return False
            if op == "gte" and actual < value:
                return False
        return True

    def _resolve_resource_target_player(self, target, run):
        if target == "self_resource":
            return run["controller"]
        if isinstance(target, str) and target.startswith("$"):
            binding = run["bindings"].get(target[1:])
            if binding is None:
                raise EffectExecutionError(f"unbound target reference: {target}")
            if binding.get("slot") is None and binding.get("id") == "self_resource":
                return binding["player"]
        return None

    def _source_slot(self, run):
        if run.get("source_slot") is None:
            return None
        slot = self.state.get_slot(run["controller"], run["source_slot"])
        if slot.get("unit_id") is None:
            return None
        return slot

    def _pick_token_spec(self, token_specs, unit_count):
        for token_spec in token_specs:
            if "unit_count_lte" in token_spec and unit_count <= int(token_spec["unit_count_lte"]):
                return token_spec
            if "unit_count_gte" in token_spec and unit_count >= int(token_spec["unit_count_gte"]):
                return token_spec
            if "unit_count" in token_spec and unit_count == int(token_spec["unit_count"]):
                return token_spec
        return None

    def _resolve_token_card_id(self, controller, token_spec):
        explicit_id = token_spec.get("card_id")
        if explicit_id:
            prefix = ""
            if isinstance(explicit_id, str) and "/" not in explicit_id:
                source_id = token_spec.get("source_card_id")
                if isinstance(source_id, str) and "/" in source_id:
                    prefix = source_id.split("/", 1)[0] + "/"
            candidate = f"{prefix}{explicit_id}"
            if self.cards.get(candidate) is not None:
                return candidate
            if self.cards.get(explicit_id) is not None:
                return explicit_id
        tokens = self.state.get_player_state(controller).get("tokens") or []
        wanted_name = (token_spec.get("name") or "").lower()
        for token_id in tokens:
            card = self.cards.get(token_id) or {}
            name = (card.get("name") or "").lower()
            if wanted_name and wanted_name in name:
                return token_id
        for token_id in tokens:
            card = self.cards.get(token_id) or {}
            if (
                int(card.get("ap") or 0) == int(token_spec.get("ap") or -1)
                and int(card.get("hp") or 0) == int(token_spec.get("hp") or -1)
            ):
                return token_id
        return None
