"""Runtime facade：唯一的合法性驗證與執行邊界。

單一 resolve pipeline：

    parsed command ─→ validate ─→ mutate（state_store）─→ events
        └→ trigger detect ─→ queue ─→ interpret（LLM）─→ spec gate
              └→ target pending choice / execute primitives ─→ events ─→ ...

resolve loop 在每次 effect apply 後持續執行 trigger detect / queue /
interpret / execute，直到沒有新 trigger 或需要玩家選擇為止。
"""

from __future__ import annotations

import logging

from .. import config
from ..effects.interpreter import InterpretationError
from .command_parser import parse_attack_target_ref, parse_slot_ref
from .effect_engine import EffectEngine, EffectExecutionError, new_effect_run
from .trigger_system import TriggerSystem


logger = logging.getLogger(__name__)


class Runtime:
    def __init__(
        self,
        state_store,
        card_database,
        rules_index,
        effect_interpreter,
        gameplay_logger,
    ):
        self.state = state_store
        self.cards = card_database
        self.rules_index = rules_index
        self.interpreter = effect_interpreter
        self.gameplay_logger = gameplay_logger
        self.effect_engine = EffectEngine(state_store, card_database, rules_index)
        self.trigger_system = TriggerSystem(state_store, rules_index)

    # ==================================================================
    # opening
    # ==================================================================

    def start_opening_sequence(self, first_player=None, decision_player=None):
        self._log_system("opening_environment_ready", "初始環境設置完成，等待開局決策。")
        if first_player is not None:
            self._set_turn_order(first_player)
            self._begin_opening_hands()
            return
        if decision_player is None:
            decision_player = self.state.choose_random_player()
        self.state.set_decision_player(decision_player)
        self._enqueue_choice({
            "type": "choose_turn_order",
            "player_id": decision_player,
            "message": "請選擇先攻或後攻",
            "options": [
                {"id": "go_first", "label": "先攻"},
                {"id": "go_second", "label": "後攻"},
            ],
        })

    def _set_turn_order(self, first_player):
        second_player = self.state.get_other_player(first_player)
        self.state.set_first_player(first_player)
        self.state.set_second_player(second_player)
        self.state.set_active_player(first_player)
        self.state.set_priority_player(first_player)

    def _begin_opening_hands(self):
        self.state.shuffle_main_deck("P1")
        self.state.shuffle_main_deck("P2")
        self.state.draw_cards("P1", config.OPENING_HAND_SIZE)
        self.state.draw_cards("P2", config.OPENING_HAND_SIZE)
        first_player = self.state.get_first_player()
        self._log_system(
            "game_started",
            f"先後攻已確定，{first_player} 為先攻，雙方已完成起手抽牌。",
        )
        self._enqueue_choice(self._build_mulligan_choice(first_player))

    def _build_mulligan_choice(self, player_id):
        return {
            "type": "mulligan",
            "player_id": player_id,
            "message": "請決定是否保留起手牌",
            "options": [
                {"id": "keep", "label": "保留"},
                {"id": "redraw", "label": "重抽"},
            ],
        }

    def _finish_opening_setup(self):
        self.state.place_shields("P1", config.SHIELD_COUNT)
        self.state.place_shields("P2", config.SHIELD_COUNT)
        self.state.deploy_ex_base("P1")
        self.state.deploy_ex_base("P2")
        self.state.set_ex_resource(self.state.get_second_player(), 1)
        self.state.set_turn(1)
        self.state.set_phase("start")
        self.state.set_step(None)
        self.state.set_priority_player(None)
        self.state.clear_action_window()
        self._log_system("rule_event", "開局設置完成，進入先攻玩家的開始階段。")

    # ==================================================================
    # resolve loop / phase machine
    # ==================================================================

    def advance_until_decision_or_stable(self):
        while True:
            if self.is_game_over():
                return
            if self.has_pending_choice():
                return
            self._recompute_continuous_effects()
            if self.trigger_system.has_waiting_trigger():
                self.resolve_next_trigger()
                continue
            if self.state.needs_action_window():
                return
            if self._advance_phase_step_if_needed():
                continue
            return

    def is_game_over(self):
        return self.state.get_state().get("game_over", False)

    def get_winner(self):
        return self.state.get_state().get("winner")

    def has_pending_choice(self):
        return self.state.peek_pending_choice() is not None

    def _advance_phase_step_if_needed(self):
        phase = self.state.get_phase()
        step = self.state.get_step()
        if phase == "start":
            self._run_start_phase()
            return True
        if phase == "draw":
            self._run_draw_phase()
            return True
        if phase == "resource":
            self._run_resource_phase()
            return True
        if phase == "battle" and step == "attack":
            self._run_battle_block_setup()
            return True
        if phase == "battle" and step == "damage":
            self._run_battle_damage_step()
            return True
        if phase == "battle" and step == "battle_end":
            self._run_battle_end_step()
            return True
        if phase == "end" and step == "end_step":
            self._run_end_step()
            return True
        if phase == "end" and step == "hand":
            self._run_hand_step()
            return True
        if phase == "end" and step == "cleanup":
            self._run_cleanup_step()
            return True
        return False

    def _run_start_phase(self):
        active_player = self.state.get_active_player()
        self.state.ready_units_and_base(active_player)
        self.state.increment_turns_on_field(active_player)
        self.state.set_phase("draw")
        self.state.set_step(None)
        self._log_system("phase_changed", f"{active_player} 的開始階段完成，進入抽牌階段。")

    def _run_draw_phase(self):
        active_player = self.state.get_active_player()
        drawn = self.state.draw_one_card(active_player)
        if drawn is None:
            winner = self.state.get_other_player(active_player)
            self.state.mark_game_over(winner=winner, reason="deck_out")
            self._log_system("rule_event", f"{active_player} 抽牌時牌庫為空，{winner} 獲勝。")
            return
        self.state.set_phase("resource")
        self.state.set_step(None)
        self._log_system("phase_changed", f"{active_player} 抽 1 張牌，進入資源階段。")

    def _run_resource_phase(self):
        active_player = self.state.get_active_player()
        deployed = self.state.deploy_resource_from_deck(active_player)
        self.state.set_phase("main")
        self.state.set_step(None)
        self.state.set_priority_player(active_player)
        message = f"{active_player} 進入主要階段。"
        if deployed:
            message = f"{active_player} 部署 1 張資源，進入主要階段。"
        self._log_system("phase_changed", message)

    def _run_battle_block_setup(self):
        defender = self.state.get_other_player(self.state.get_active_player())
        if self._defender_has_legal_blocker(defender):
            self.state.set_step("block")
            self.state.set_priority_player(defender)
            self._log_system("phase_changed", "進入阻擋步驟。")
            return
        self._enter_battle_action_step(defender, note="對手沒有可用的阻擋者，直接進入戰鬥 Action Step。")

    def _defender_has_legal_blocker(self, defender):
        battle_context = self.state.get_battle_context() or {}
        if battle_context.get("blocker_slot") is not None:
            return False
        for slot in self.state.iter_units(defender):
            if self.state.can_block_with_unit(defender, slot["slot"]):
                return True
        return False

    def _enter_battle_action_step(self, priority_player, note):
        self.state.set_step("action")
        self.state.start_action_window(origin="battle", priority_player=priority_player)
        self._log_system("phase_changed", note)

    def _run_battle_damage_step(self):
        battle_context = self.state.get_battle_context() or {}
        if battle_context:
            self._apply_battle_damage(battle_context)
        if self.is_game_over():
            return
        self.state.set_step("battle_end")
        self._log_system("phase_changed", "戰鬥傷害步驟完成，進入戰鬥結束步驟。")

    def _run_battle_end_step(self):
        self.state.clear_battle_context()
        self.state.clear_action_window()
        self.state.set_phase("main")
        self.state.set_step(None)
        self.state.set_priority_player(self.state.get_active_player())
        self._log_system("phase_changed", "戰鬥結束，回到主要階段。")

    def _run_end_step(self):
        active_player = self.state.get_active_player()
        triggers = self.trigger_system.detect_end_of_turn(active_player)
        self.trigger_system.enqueue_all(triggers)
        self.state.set_step("hand")
        self._log_system("phase_changed", "結束階段 Action Step 完成，進入手牌調整步驟。")

    def _run_hand_step(self):
        active_player = self.state.get_active_player()
        hand_count = len(self.state.get_player_state(active_player)["hand"])
        if hand_count > config.HAND_LIMIT:
            self._create_cleanup_discard_choice(active_player)
            return
        self.state.set_step("cleanup")
        self._log_system("phase_changed", "手牌調整步驟完成，進入清理步驟。")

    def _create_cleanup_discard_choice(self, player_id):
        hand = self.state.get_player_state(player_id)["hand"]
        self._enqueue_choice({
            "type": "discard_to_hand_limit",
            "player_id": player_id,
            "message": "手牌超過上限，請選擇 1 張手牌棄置。",
            "hidden_options": True,
            "options": [{"id": card_id, "label": card_id} for card_id in hand],
        })

    def _run_cleanup_step(self):
        current_player = self.state.get_active_player()
        next_player = self.state.get_other_player(current_player)
        self.state.clear_temporary_modifiers()
        self.state.clear_action_window()
        self.state.clear_battle_context()
        self.state.clear_once_per_turn()
        self.state.set_active_player(next_player)
        self.state.set_priority_player(None)
        self.state.set_turn(self.state.get_turn() + 1)
        self.state.set_phase("start")
        self.state.set_step(None)
        self._log_system(
            "phase_changed",
            f"{current_player} 的回合結束，輪到 {next_player} 的開始階段。",
        )

    # ==================================================================
    # command resolution
    # ==================================================================

    def resolve_command(self, parsed_command):
        if self.has_pending_choice():
            raise ValueError("有等待中的選擇，請先用 choose 回應。")
        command_type = parsed_command.command_type
        logger.info(
            "resolve_command game=%s player=%s type=%s raw=%s",
            self.state.get_game_id(), parsed_command.player_id, command_type, parsed_command.raw_text,
        )
        if command_type == "pass":
            self._resolve_pass(parsed_command)
        elif command_type == "play_card":
            self._resolve_play_card(parsed_command)
        elif command_type == "pair":
            self._resolve_pair(parsed_command)
        elif command_type == "attack":
            self._resolve_attack(parsed_command)
        elif command_type == "block":
            self._resolve_block(parsed_command)
        elif command_type == "activate_effect":
            self._resolve_activate_effect(parsed_command)
        elif command_type == "choose":
            raise ValueError("目前沒有等待中的選擇，不能使用 choose。")
        else:
            raise ValueError(f"不支援的指令類型：{command_type}")
        self.advance_until_decision_or_stable()
        self.state.save_snapshot()

    # --- pass ---------------------------------------------------------

    def _resolve_pass(self, parsed_command):
        phase = self.state.get_phase()
        step = self.state.get_step()
        player_id = parsed_command.player_id
        if self.state.get_priority_player() != player_id:
            raise ValueError("目前不是你的優先權。")
        consider = parsed_command.consider

        if phase == "main":
            standby_player = self.state.get_other_player(self.state.get_active_player())
            self.state.set_phase("end")
            self.state.set_step("action")
            self.state.start_action_window(origin="end", priority_player=standby_player)
            self._log_system(
                "priority_passed",
                self._with_consider(f"{player_id} 宣告結束主要階段，進入結束階段 Action Step。", consider),
            )
            return

        if phase == "battle" and step == "block":
            defender = player_id
            self._log_system(
                "priority_passed",
                self._with_consider(f"{player_id} 放棄阻擋，進入戰鬥 Action Step。", consider),
            )
            self._enter_battle_action_step(defender, note=f"戰鬥 Action Step 開始，由 {defender} 先取得優先權。")
            return

        if (phase == "battle" and step == "action") or (phase == "end" and step == "action"):
            next_phase, next_step = ("battle", "damage") if phase == "battle" else ("end", "end_step")
            pass_count = self.state.record_priority_pass(player_id)
            if pass_count >= 2:
                self.state.clear_action_window()
                self.state.set_phase(next_phase)
                self.state.set_step(next_step)
                self.state.set_priority_player(None)
                self._log_system(
                    "priority_passed",
                    self._with_consider(f"{player_id} 讓過。雙方連續讓過，推進到 {next_phase} / {next_step}。", consider),
                )
                return
            next_player = self.state.get_other_player(player_id)
            self.state.set_priority_player(next_player)
            self._log_system(
                "priority_passed",
                self._with_consider(f"{player_id} 讓過，現在輪到 {next_player}。", consider),
            )
            return

        raise ValueError(f"pass 不能用於 phase={phase} step={step}。")

    # --- play_card ----------------------------------------------------

    def _resolve_play_card(self, parsed_command):
        player_id = parsed_command.player_id
        card_id = parsed_command.source_ref
        card = self.cards.get(card_id)
        if card is None:
            raise ValueError(f"找不到卡牌：{card_id}")
        card_type = card.get("cardType")
        if card_type == "unit":
            self._play_unit(parsed_command, card)
        elif card_type == "command":
            self._play_command_card(parsed_command, card)
        elif card_type == "base":
            self._play_base(parsed_command, card)
        else:
            raise ValueError(f"play_card 不支援的卡牌類型：{card_type}（pilot 請用 pair 指令）。")

    def _require_main_priority(self, player_id):
        if self.state.get_phase() != "main" or self.state.get_priority_player() != player_id:
            raise ValueError("目前不是你的主要階段行動時機。")

    def _check_level_and_cost(self, player_id, card):
        if self.state.total_level(player_id) < int(card.get("level") or 0):
            raise ValueError("目前等級不足，不能使用這張卡。")
        if self.state.available_cost_resources(player_id) < int(card.get("cost") or 0):
            raise ValueError("目前可支付資源不足，不能使用這張卡。")

    def _play_unit(self, parsed_command, card):
        player_id = parsed_command.player_id
        self._require_main_priority(player_id)
        if not parsed_command.args:
            raise ValueError("部署 Unit 需要指定欄位，例如：play_card st01/ST01-008 0")
        try:
            slot_index = int(parsed_command.args[0])
        except ValueError as exc:
            raise ValueError("部署欄位必須是數字。") from exc
        if slot_index not in self.state.find_empty_slots(player_id):
            raise ValueError(f"欄位 {slot_index} 不能部署。")
        self._check_level_and_cost(player_id, card)

        card_id = parsed_command.source_ref
        self.state.pay_cost(player_id, int(card.get("cost") or 0))
        keywords = self.rules_index.keywords(card_id)
        self.state.deploy_unit_from_hand(player_id, card_id, slot_index, keywords=keywords)
        self.state.record_priority_action(player_id)
        self._log_command(
            parsed_command,
            f"{player_id} 部署 {card_id} 到 {slot_index} 號位。",
        )
        self._handle_events([
            {"type": "unit_deployed", "player": player_id, "slot": slot_index, "card_id": card_id},
        ])

    def _play_command_card(self, parsed_command, card):
        player_id = parsed_command.player_id
        phase = self.state.get_phase()
        step = self.state.get_step()
        in_action_window = (phase == "battle" and step == "action") or (phase == "end" and step == "action")
        if phase == "main":
            timing = "MAIN"
            self._require_main_priority(player_id)
        elif in_action_window:
            timing = "ACTION"
            if self.state.get_priority_player() != player_id:
                raise ValueError("目前不是你的優先權。")
        else:
            raise ValueError("目前時機不能使用 Command 卡。")

        if timing not in self.rules_index.play_windows(parsed_command.source_ref):
            raise ValueError(f"這張 Command 卡不能在 {timing} 時機使用。")
        self._check_level_and_cost(player_id, card)

        spec = self._interpret(card, timing, controller=player_id, source_zone="hand")
        if spec.get("status") == "unsupported":
            raise ValueError(
                f"這張卡的效果目前不被支援：{spec.get('unsupported_capabilities')}"
            )

        card_id = parsed_command.source_ref
        self.state.pay_cost(player_id, int(card.get("cost") or 0))
        self.state.remove_from_hand(player_id, card_id)
        self.state.record_priority_action(player_id)
        self._log_command(parsed_command, f"{player_id} 使用 Command 卡 {card_id}。")
        run = new_effect_run(
            spec,
            controller=player_id,
            source_card_id=card_id,
            source_zone="command",
        )
        run["after_default"] = "trash"
        self._proceed_effect_run(run)

    def _play_base(self, parsed_command, card):
        player_id = parsed_command.player_id
        self._require_main_priority(player_id)
        if self.state.base_alive(player_id):
            raise ValueError("基地區已有基地，不能再部署基地。")
        self._check_level_and_cost(player_id, card)
        card_id = parsed_command.source_ref
        self.state.pay_cost(player_id, int(card.get("cost") or 0))
        self.state.remove_from_hand(player_id, card_id)
        self.state.deploy_base(player_id, card_id, ap=card.get("ap"), hp=card.get("hp"))
        self.state.record_priority_action(player_id)
        self._log_command(parsed_command, f"{player_id} 部署基地 {card_id}。")
        self._handle_events([
            {"type": "base_deployed", "player": player_id, "card_id": card_id},
        ])

    # --- pair ---------------------------------------------------------

    def _resolve_pair(self, parsed_command):
        player_id = parsed_command.player_id
        self._require_main_priority(player_id)
        card_id = parsed_command.source_ref
        card = self.cards.get(card_id)
        if card is None:
            raise ValueError(f"找不到卡牌：{card_id}")

        if card.get("cardType") == "pilot":
            pilot_name = card.get("name")
            ap_bonus, hp_bonus = card.get("ap"), card.get("hp")
        else:
            designation = self.rules_index.pilot_designation(card_id)
            if designation is None:
                raise ValueError("這張卡不能作為 Pilot 配對。")
            pilot_name = designation["name"]
            ap_bonus, hp_bonus = designation["ap"], designation["hp"]

        slot_index = parse_slot_ref(parsed_command.target_ref)
        slot = self.state.get_slot(player_id, slot_index)
        if slot.get("unit_id") is None:
            raise ValueError(f"{slot_index} 號位沒有 Unit。")
        if slot.get("pilot_id") is not None:
            raise ValueError(f"{slot_index} 號位已有 Pilot。")
        self._check_level_and_cost(player_id, card)

        self.state.pay_cost(player_id, int(card.get("cost") or 0))
        slot = self.state.pair_pilot(
            player_id, slot_index, card_id,
            pilot_name=pilot_name, ap_bonus=ap_bonus, hp_bonus=hp_bonus,
        )
        self.state.record_priority_action(player_id)
        link_note = "（達成 Link）" if slot.get("is_link") else ""
        self._log_command(
            parsed_command,
            f"{player_id} 將 {card_id} 配對到 {slot_index} 號位的 {slot['unit_id']}{link_note}。",
        )
        self._handle_events([
            {
                "type": "pairing_complete",
                "player": player_id,
                "slot": slot_index,
                "unit_id": slot["unit_id"],
                "pilot_id": card_id,
            },
        ])

    # --- attack / block -----------------------------------------------

    def _resolve_attack(self, parsed_command):
        player_id = parsed_command.player_id
        self._require_main_priority(player_id)
        attacker_slot = parse_slot_ref(parsed_command.source_ref)
        if not self.state.can_attack_with_unit(player_id, attacker_slot):
            raise ValueError(f"{attacker_slot} 號位目前不能攻擊。")

        target_kind, target_slot = parse_attack_target_ref(parsed_command.target_ref or "opponent_base")
        opponent = self.state.get_other_player(player_id)
        attacker = self.state.get_slot(player_id, attacker_slot)

        if target_kind == "base":
            if not self.rules_index.can_attack_player(attacker["unit_id"]):
                raise ValueError("這個 Unit 不能以對手玩家／防禦層為攻擊目標。")
        else:
            enemy_slot = self.state.get_slot(opponent, target_slot)
            if enemy_slot.get("unit_id") is None:
                raise ValueError(f"對手 {target_slot} 號位沒有 Unit。")
            if enemy_slot.get("status") != "rested":
                raise ValueError("只能攻擊 rested 的敵方 Unit。")

        self.state.rest_unit(player_id, attacker_slot)
        self.state.set_battle_context({
            "attacker_player": player_id,
            "attacker_slot": attacker_slot,
            "defender_player": opponent,
            "target_kind": target_kind,
            "target_slot": target_slot,
            "blocker_slot": None,
        })
        self.state.set_phase("battle")
        self.state.set_step("attack")
        self.state.set_priority_player(None)
        target_text = (
            "對手防禦層" if target_kind == "base" else f"對手 {target_slot} 號位"
        )
        self._log_command(
            parsed_command,
            f"{player_id} 以 {attacker_slot} 號位攻擊{target_text}。",
        )
        self._handle_events([
            {"type": "attack_declared", "player": player_id, "slot": attacker_slot},
        ])

    def _resolve_block(self, parsed_command):
        if self.state.get_phase() != "battle" or self.state.get_step() != "block":
            raise ValueError("目前不是阻擋時機。")
        player_id = parsed_command.player_id
        if self.state.get_priority_player() != player_id:
            raise ValueError("目前不是你的阻擋優先權。")
        blocker_slot = parse_slot_ref(parsed_command.source_ref)
        if not self.state.can_block_with_unit(player_id, blocker_slot):
            raise ValueError(f"{blocker_slot} 號位目前不能阻擋。")

        battle_context = self.state.get_battle_context() or {}
        self.state.rest_unit(player_id, blocker_slot)
        battle_context["blocker_slot"] = blocker_slot
        self.state.set_battle_context(battle_context)
        self._log_command(
            parsed_command,
            f"{player_id} 以 {blocker_slot} 號位阻擋攻擊。",
        )
        self._enter_battle_action_step(player_id, note=f"戰鬥 Action Step 開始，由 {player_id} 先取得優先權。")

    # --- activate_effect ------------------------------------------------

    def _resolve_activate_effect(self, parsed_command):
        player_id = parsed_command.player_id
        self._require_main_priority(player_id)
        source_ref = (parsed_command.source_ref or "").strip().lower()
        if source_ref not in {"base", "my_base"}:
            raise ValueError("activate_effect 目前只支援 base（[Activate/Main] 能力）。")
        base = self.state.get_base(player_id)
        if not base or not base.get("alive", True) or base.get("card_id") == "EX-BASE":
            raise ValueError("你沒有可發動能力的基地。")
        card = self.cards.get(base["card_id"])
        if card is None or not self.rules_index.has_activated_main(base["card_id"]):
            raise ValueError("這個基地沒有 [Activate/Main] 能力。")

        spec = self._interpret(card, "ACTIVATE_MAIN", controller=player_id, source_zone="base")
        if spec.get("status") == "unsupported":
            raise ValueError(f"這個能力目前不被支援：{spec.get('unsupported_capabilities')}")

        once_key = None
        if spec.get("once_per_turn"):
            once_key = self.state.once_per_turn_key(player_id, "base", base["card_id"])
            if self.state.is_once_per_turn_used(once_key):
                raise ValueError("這個能力本回合已使用過。")

        cost = spec.get("cost") or {}
        resource_cost = int(cost.get("resources") or 0)
        if self.state.available_cost_resources(player_id) < resource_cost:
            raise ValueError("資源不足，無法支付能力費用。")
        if cost.get("rest_source"):
            self.state.rest_base(player_id)
        if resource_cost > 0:
            self.state.pay_cost(player_id, resource_cost)
        if once_key:
            self.state.mark_once_per_turn_used(once_key)
        self.state.record_priority_action(player_id)
        self._log_command(parsed_command, f"{player_id} 發動基地 {base['card_id']} 的能力。")
        run = new_effect_run(
            spec,
            controller=player_id,
            source_card_id=base["card_id"],
            source_zone="base",
        )
        self._proceed_effect_run(run)

    # ==================================================================
    # pending choice resolution
    # ==================================================================

    def resolve_pending_choice(self, parsed_command, pending_choice):
        if self.state.peek_pending_choice() is not pending_choice:
            raise ValueError("pending choice queue head changed before resolution")
        if parsed_command.command_type != "choose":
            raise ValueError("等待中的選擇必須用 choose <option_id> 回應。")
        if parsed_command.player_id != pending_choice.get("player_id"):
            raise ValueError("這個選擇不屬於你。")
        choice_type = pending_choice["type"]
        handler = {
            "choose_turn_order": self._resolve_turn_order_choice,
            "mulligan": self._resolve_mulligan_choice,
            "discard_to_hand_limit": self._resolve_discard_choice,
            "effect_target": self._resolve_effect_target_choice,
            "optional_effect": self._resolve_optional_effect_choice,
        }.get(choice_type)
        if handler is None:
            raise ValueError(f"unknown pending choice type: {choice_type}")
        handler(parsed_command, pending_choice)
        self.advance_until_decision_or_stable()
        self.state.save_snapshot()

    def _option_ids(self, pending_choice):
        return {option.get("id") for option in pending_choice.get("options", [])}

    def _resolve_turn_order_choice(self, parsed_command, pending_choice):
        choice_id = parsed_command.choice_id
        if choice_id not in {"go_first", "go_second"}:
            raise ValueError("turn order choice must be go_first or go_second")
        decision_player = pending_choice["player_id"]
        first_player = decision_player
        if choice_id == "go_second":
            first_player = self.state.get_other_player(decision_player)
        self.state.pop_pending_choice()
        self._set_turn_order(first_player)
        self._log_system(
            "choice_resolved",
            self._with_consider(
                f"{decision_player} 選擇由 {first_player} 先攻。", parsed_command.consider
            ),
        )
        self._begin_opening_hands()

    def _resolve_mulligan_choice(self, parsed_command, pending_choice):
        choice_id = parsed_command.choice_id
        if choice_id not in {"keep", "redraw"}:
            raise ValueError("mulligan choice must be keep or redraw")
        player_id = pending_choice["player_id"]
        if choice_id == "redraw":
            self.state.return_hand_to_deck_for_mulligan(player_id)
            self.state.draw_cards(player_id, config.OPENING_HAND_SIZE)
        self.state.mark_mulligan_done(player_id)
        self.state.pop_pending_choice()
        action_text = "重抽" if choice_id == "redraw" else "保留"
        self._log_system(
            "mulligan_resolved",
            self._with_consider(f"{player_id} 選擇{action_text}起手牌。", parsed_command.consider),
        )
        if player_id == self.state.get_first_player():
            self._enqueue_choice(self._build_mulligan_choice(self.state.get_second_player()))
            return
        self._finish_opening_setup()

    def _resolve_discard_choice(self, parsed_command, pending_choice):
        choice_id = parsed_command.choice_id
        if choice_id not in self._option_ids(pending_choice):
            raise ValueError("discard choice must be one of the visible hand card ids")
        player_id = pending_choice["player_id"]
        self.state.discard_from_hand(player_id, choice_id)
        self.state.pop_pending_choice()
        self._log_system(
            "hand_limit_discard_resolved",
            self._with_consider(f"{player_id} 棄掉 1 張手牌以符合手牌上限。", parsed_command.consider),
        )
        if len(self.state.get_player_state(player_id)["hand"]) > config.HAND_LIMIT:
            self._create_cleanup_discard_choice(player_id)
            return
        self.state.set_step("cleanup")

    def _resolve_effect_target_choice(self, parsed_command, pending_choice):
        choice_id = parsed_command.choice_id
        options = {option["id"]: option for option in pending_choice.get("options", [])}
        if choice_id not in options:
            raise ValueError("effect target must be one of the offered options")
        self.state.pop_pending_choice()
        run = pending_choice["run"]
        self.effect_engine.bind_target(run, options[choice_id])
        self._log_system(
            "choice_resolved",
            self._with_consider(
                f"{pending_choice['player_id']} 為 {run['source_card_id']} 的效果選擇目標 {choice_id}。",
                parsed_command.consider,
            ),
        )
        self._proceed_effect_run(run)

    def _resolve_optional_effect_choice(self, parsed_command, pending_choice):
        choice_id = parsed_command.choice_id
        if choice_id not in {"activate", "decline"}:
            raise ValueError("optional effect choice must be activate or decline")
        self.state.pop_pending_choice()
        run = pending_choice["run"]
        if choice_id == "decline":
            self._log_system(
                "choice_resolved",
                self._with_consider(
                    f"{pending_choice['player_id']} 選擇不發動 {run['source_card_id']} 的效果。",
                    parsed_command.consider,
                ),
            )
            self._dispose_effect_source(run)
            return
        self._log_system(
            "choice_resolved",
            self._with_consider(
                f"{pending_choice['player_id']} 選擇發動 {run['source_card_id']} 的效果。",
                parsed_command.consider,
            ),
        )
        run["optional_confirmed"] = True
        self._proceed_effect_run(run)

    # ==================================================================
    # effect run lifecycle
    # ==================================================================

    def _interpret(self, card, timing, controller, source_zone):
        context = {
            "game_id": self.state.get_game_id(),
            "controller": controller,
            "source_zone": source_zone,
            "board_summary": self._board_summary(),
        }
        try:
            return self.interpreter.interpret(card, timing, context)
        except InterpretationError as exc:
            raise ValueError(f"效果解讀失敗（interpretation problem）：{exc}") from exc

    def _board_summary(self):
        snapshot = self.state.build_snapshot()
        return {
            "turn": snapshot["turn"],
            "phase": snapshot["phase"],
            "p1_units": snapshot["p1"]["board"]["units"],
            "p2_units": snapshot["p2"]["board"]["units"],
        }

    def resolve_next_trigger(self):
        trigger = self.trigger_system.pop_next_trigger()
        card = self.cards.get(trigger["card_id"])
        if card is None:
            self.gameplay_logger.log_trigger_skipped(
                game_id=self.state.get_game_id(),
                trigger_context=trigger,
                reason=f"unknown card: {trigger['card_id']}",
            )
            return
        try:
            spec = self._interpret(
                card,
                trigger["timing"],
                controller=trigger["controller"],
                source_zone=trigger["source_zone"],
            )
        except ValueError as exc:
            self.gameplay_logger.log_trigger_skipped(
                game_id=self.state.get_game_id(),
                trigger_context=trigger,
                reason=str(exc),
            )
            self._dispose_trigger_source(trigger)
            return

        if spec.get("status") == "unsupported":
            self.gameplay_logger.log_trigger_skipped(
                game_id=self.state.get_game_id(),
                trigger_context=trigger,
                reason=f"unsupported capabilities: {spec.get('unsupported_capabilities')}",
            )
            self._dispose_trigger_source(trigger)
            return

        if spec.get("once_per_turn"):
            once_key = self.state.once_per_turn_key(
                trigger["controller"],
                f"slot_{trigger.get('source_slot')}",
                f"{trigger['card_id']}@{trigger['timing']}",
            )
            if self.state.is_once_per_turn_used(once_key):
                return
            self.state.mark_once_per_turn_used(once_key)

        run = new_effect_run(
            spec,
            controller=trigger["controller"],
            source_card_id=trigger["card_id"],
            source_slot=trigger.get("source_slot"),
            source_zone=trigger["source_zone"],
        )
        run["after_default"] = trigger.get("after_default")
        run["trigger_context"] = trigger

        if spec.get("optional") and not run.get("optional_confirmed"):
            self._enqueue_choice({
                "type": "optional_effect",
                "player_id": trigger["controller"],
                "message": f"{trigger['card_id']} 的 [{trigger['timing']}] 效果可以發動，是否發動？",
                "options": [
                    {"id": "activate", "label": "發動"},
                    {"id": "decline", "label": "不發動"},
                ],
                "run": run,
            })
            return

        self._proceed_effect_run(run)

    def _proceed_effect_run(self, run):
        """推進一個 effect run：補目標 → 全綁定後執行 → 處理事件。"""
        requirement = self.effect_engine.next_unbound_requirement(run)
        while requirement is not None:
            options = self.effect_engine.enumerate_targets(requirement, run)
            if not options:
                # 沒有合法目標：效果落空
                self._log_system(
                    "effect_resolved",
                    f"{run['source_card_id']} 的效果沒有合法目標，效果落空。",
                )
                self._dispose_effect_source(run)
                return
            if len(options) == 1 and requirement.get("card_type") in {"resource", "shield"}:
                # 資源／盾牌同質，自動綁定
                self.effect_engine.bind_target(run, options[0])
                requirement = self.effect_engine.next_unbound_requirement(run)
                continue
            self._enqueue_choice({
                "type": "effect_target",
                "player_id": run["controller"],
                "message": f"{run['source_card_id']} 的效果需要選擇目標。",
                "options": options,
                "run": run,
            })
            return

        try:
            events, messages = self.effect_engine.execute(run)
        except EffectExecutionError as exc:
            self.gameplay_logger.log_trigger_skipped(
                game_id=self.state.get_game_id(),
                trigger_context=run.get("trigger_context") or {"card_id": run["source_card_id"]},
                reason=f"effect execution problem: {exc}",
            )
            self._dispose_effect_source(run)
            return

        for message in messages:
            self._log_system("effect_resolved", message)
        chained = self._handle_events(events, parent_run=run)
        if not chained:
            self._dispose_effect_source(run)

    def _dispose_trigger_source(self, trigger):
        if trigger.get("after_default") == "trash":
            self.state.add_to_trash(trigger["controller"], trigger["card_id"])

    def _dispose_effect_source(self, run):
        if run.get("after_default") == "trash" and not run.get("source_consumed"):
            self.state.add_to_trash(run["controller"], run["source_card_id"])

    def _handle_events(self, events, parent_run=None):
        """處理 engine 事件：trigger 偵測 + 連鎖 effect run。回傳是否有 chained run 接手來源卡。"""
        chained = False
        for event in events:
            if event.get("type") == "game_over":
                continue
            if event.get("type") == "activate_ability_requested":
                card = self.cards.get(event["card_id"])
                if card is None:
                    continue
                try:
                    spec = self._interpret(
                        card, "MAIN",
                        controller=event["player"],
                        source_zone=parent_run["source_zone"] if parent_run else "battle_area",
                    )
                except ValueError as exc:
                    self._log_system("rule_event", f"{event['card_id']} 的連鎖效果解讀失敗：{exc}")
                    continue
                if spec.get("status") == "unsupported":
                    self._log_system("rule_event", f"{event['card_id']} 的連鎖效果不被支援。")
                    continue
                child_run = new_effect_run(
                    spec,
                    controller=event["player"],
                    source_card_id=event["card_id"],
                    source_zone=parent_run["source_zone"] if parent_run else "battle_area",
                )
                if parent_run is not None:
                    child_run["after_default"] = parent_run.get("after_default")
                    chained = True
                self._proceed_effect_run(child_run)
                continue
            triggers = self.trigger_system.detect_for_event(event)
            self.trigger_system.enqueue_all(triggers)
            if event.get("type") == "shield_broken" and not triggers:
                # 沒有 [Burst] → 盾牌卡直接進廢棄區
                self.state.add_to_trash(event["player"], event["card_id"])
                self._log_system(
                    "rule_event",
                    f"{event['player']} 的盾牌 {event['card_id']} 被破壞並進入廢棄區。",
                )
        return chained

    # ==================================================================
    # battle damage
    # ==================================================================

    def _apply_battle_damage(self, battle_context):
        attacker_player = battle_context["attacker_player"]
        defender_player = battle_context["defender_player"]
        attacker_slot_index = battle_context["attacker_slot"]
        attacker = self.state.get_slot(attacker_player, attacker_slot_index)
        if attacker["unit_id"] is None:
            return

        attacker_ap = attacker["ap"]
        events = []

        def fight_unit(defender_slot_index):
            defender_slot = self.state.get_slot(defender_player, defender_slot_index)
            if defender_slot["unit_id"] is None:
                return
            defender_ap = defender_slot["ap"]
            self.state.deal_damage_to_unit(defender_player, defender_slot_index, attacker_ap)
            self.state.deal_damage_to_unit(attacker_player, attacker_slot_index, defender_ap)
            self._log_system(
                "rule_event",
                f"戰鬥傷害結算：{attacker_player} 的 {attacker_slot_index} 號位與 "
                f"{defender_player} 的 {defender_slot_index} 號位互相造成傷害。",
            )
            for player_id, slot_index in (
                (defender_player, defender_slot_index),
                (attacker_player, attacker_slot_index),
            ):
                destroyed = self.state.destroy_unit_if_lethal(player_id, slot_index)
                if destroyed:
                    events.append({
                        "type": "unit_destroyed",
                        "player": player_id,
                        "slot": slot_index,
                        "card_id": destroyed,
                    })
                    self._log_system("rule_event", f"{player_id} 的 {destroyed} 被擊破並進入廢棄區。")

        blocker_slot_index = battle_context.get("blocker_slot")
        if blocker_slot_index is not None:
            fight_unit(blocker_slot_index)
        elif battle_context.get("target_kind") == "unit":
            fight_unit(battle_context.get("target_slot"))
        else:
            result = self.state.deal_damage_to_defense(defender_player, attacker_ap)
            if result["target"] == "player":
                self.state.mark_game_over(winner=attacker_player, reason="player_damage")
                self._log_system("rule_event", f"{attacker_player} 直擊玩家並獲勝。")
            elif result["target"] == "base":
                note = "並摧毀基地" if result.get("destroyed") else ""
                self._log_system(
                    "rule_event",
                    f"{attacker_player} 對對手基地造成 {attacker_ap} 點傷害{note}。",
                )
            elif result["target"] == "shield":
                self._log_system("rule_event", f"{attacker_player} 擊破 {defender_player} 1 面盾牌（{result['card_id']}）。")
                events.append({
                    "type": "shield_broken",
                    "player": defender_player,
                    "card_id": result["card_id"],
                })
            else:
                self._log_system("rule_event", f"{attacker_player} 的攻擊沒有造成傷害（AP 0）。")

        self._handle_events(events)

    # ==================================================================
    # continuous effects
    # ==================================================================

    def _recompute_continuous_effects(self):
        """重算連續性修正（目前支援 [During Pair] 全體 AP 修正 pattern）。"""
        active_player = self.state.get_active_player()
        for player_id in ("P1", "P2"):
            bonus = 0
            for slot in self.state.iter_units(player_id):
                for modifier in self.rules_index.continuous_modifiers(slot["unit_id"]):
                    if modifier.get("requires_paired") and not slot.get("pilot_id"):
                        continue
                    if modifier.get("your_turn_only") and player_id != active_player:
                        continue
                    bonus += int(modifier.get("value") or 0)
            for slot in self.state.iter_units(player_id):
                if slot.get("cont_ap_mod", 0) != bonus:
                    self.state.set_continuous_ap_mod(player_id, slot["slot"], bonus)

    # ==================================================================
    # logging helpers
    # ==================================================================

    def _enqueue_choice(self, choice):
        self.state.enqueue_pending_choice(choice)
        self.gameplay_logger.log_pending_choice(
            game_id=self.state.get_game_id(),
            choice=choice,
        )
        self.state.save_snapshot()

    def _log_system(self, event_type, message):
        self.gameplay_logger.log_system_event(
            game_id=self.state.get_game_id(),
            event_type=event_type,
            payload={"message": message},
        )

    def _log_command(self, parsed_command, message):
        self.gameplay_logger.log_command_event(
            game_id=self.state.get_game_id(),
            parsed_command=parsed_command,
            message=self._with_consider(message, parsed_command.consider),
        )

    def _with_consider(self, message, consider):
        if consider:
            return f"{message} 理由：{consider}"
        return message
