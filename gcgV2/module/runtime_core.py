"""
Lean pseudo class for the V2 runtime core.

This file is intentionally simple.
It shows what the runtime should own, and what it should delegate.
"""


class RuntimeCore:
    """
    Inner game engine for one GCG match.

    Responsibilities:
    - own the real game state
    - validate commands against rules and timing
    - execute safe state changes through primitives
    - resolve triggers, rule checks, and pending choices
    - decide when the game needs player input

    Non-responsibilities:
    - do not ask AI what to do
    - do not build viewer-safe state for players
    - do not let LLM write state directly
    - do not guess missing player choices
    """

    def __init__(
        self,
        state_store,
        card_database,
        effect_interpreter,
        runtime_validator,
        primitive_executor,
        rules_management,
        trigger_system,
        gameplay_logger,
    ):
        self.state_store = state_store
        self.card_database = card_database
        self.effect_interpreter = effect_interpreter
        self.runtime_validator = runtime_validator
        self.primitive_executor = primitive_executor
        self.rules_management = rules_management
        self.trigger_system = trigger_system
        self.gameplay_logger = gameplay_logger

    def start_game(
        self,
        first_player="P1",
        decision_player=None,
        p1_deck_id="deck001",
        p2_deck_id="deck001",
    ):
        """
        Compatibility wrapper for direct runtime-driven game startup.

        The canonical path is:
        - state_store.create_game_shell()
        - gameplay_logger.open_game()
        - start_opening_sequence()
        """
        game_id = self.state_store.create_game_shell(
            p1_deck_id=p1_deck_id,
            p2_deck_id=p2_deck_id,
        )
        self.gameplay_logger.open_game(game_id)
        ##update pending choice state
        self.start_opening_sequence(
            first_player=first_player,
            decision_player=decision_player,
        )
        return game_id

    def start_opening_sequence(self, first_player=None, decision_player=None):
        """
        Bootstrap the GCG opening flow.

        This method stays lean:
        - decide whether turn order is already fixed
        - create opening pending choices
        - draw opening hands only after first/second is known
        """
        self.gameplay_logger.log_system_event(
            game_id=self.state_store.get_game_id(),
            event_type="opening_environment_ready",
            payload={
                "message": "初始環境設置完成，等待開局決策。",
                "features": self.state_store.build_snapshot(),
            },
        )

        if first_player is not None:
            self._set_turn_order(first_player)
            self._begin_opening_hands()
            return

        if decision_player is None:
            decision_player = self.state_store.choose_random_player()

        self.state_store.set_decision_player(decision_player)
        choice = {
            "type": "choose_turn_order",
            "player_id": decision_player,
            "message": "請選擇先攻或後攻",
            "options": [
                {"id": "go_first", "label": "先攻"},
                {"id": "go_second", "label": "後攻"},
            ],
        }
        self.state_store.enqueue_pending_choice(choice)
        self.gameplay_logger.log_pending_choice(
            game_id=self.state_store.get_game_id(),
            choice=choice,
        )
        self.state_store.save_snapshot()

    def advance_until_decision_or_stable(self):
        """
        Auto-resolve everything that does not need a player decision.

        Example:
        - finish a deploy effect that already has all targets
        - apply rule checks after damage
        - enqueue and resolve forced triggers
        - stop when runtime reaches a pending choice or action window
        """
        while True:
            if self.is_game_over():
                return

            if self.has_pending_choice():
                return

            if self.trigger_system.has_waiting_trigger(self.state_store):
                self.resolve_next_trigger()
                continue

            if self.rules_management.has_pending_rule_check(self.state_store):
                self.apply_rule_check()
                continue

            if self.state_store.needs_action_window():
                return

            return

    def resolve_command(self, parsed_command):
        """
        Resolve one parsed player command.

        Example:
        - player says: play_card hand_3 target enemy_unit_2
        - runtime interprets it into structured intent
        - runtime validates timing, cost, and target
        - runtime executes primitives
        - runtime then runs triggers and rule checks
        """
        pending_choice = self.state_store.peek_pending_choice()
        if pending_choice is not None:
            self._resolve_pending_choice(parsed_command, pending_choice)
            return

        if getattr(parsed_command, "command_type", None) == "pass":
            # Placeholder demo behavior:
            # full turn progression is not implemented yet, so a standalone
            # pass outside an opening choice only ends the pseudo run.
            self.state_store.mark_game_over(winner=None)
            self.gameplay_logger.log_system_event(
                game_id=self.state_store.get_game_id(),
                event_type="priority_passed",
                payload={
                    "message": f"{parsed_command.player_id} 讓過。",
                    "features": self.state_store.build_snapshot(),
                },
            )
            self.state_store.save_snapshot()
            return

        resolved_intent = self.effect_interpreter.resolve_command(
            parsed_command=parsed_command,
            state=self.state_store,
            card_database=self.card_database,
        )

        validation_result = self.runtime_validator.validate_command(
            resolved_intent=resolved_intent,
            state=self.state_store,
            card_database=self.card_database,
        )

        if validation_result.status == "invalid":
            self.gameplay_logger.log_invalid_command(
                game_id=self.state_store.get_game_id(),
                parsed_command=parsed_command,
                reason=validation_result.reason,
            )
            raise ValueError(validation_result.reason)

        if validation_result.status == "pending_choice":
            self.state_store.enqueue_pending_choice(validation_result.pending_choice)
            self.gameplay_logger.log_pending_choice(
                game_id=self.state_store.get_game_id(),
                choice=validation_result.pending_choice,
            )
            return

        self.primitive_executor.execute_intent(
            resolved_intent=resolved_intent,
            state=self.state_store,
        )
        self.gameplay_logger.log_command_resolved(
            game_id=self.state_store.get_game_id(),
            parsed_command=parsed_command,
            resolved_intent=resolved_intent,
        )
        self.advance_until_decision_or_stable()

    def resolve_next_trigger(self):
        """
        Resolve the next trigger that is ready.

        Example:
        - a Unit is destroyed
        - trigger_system pops 'when destroyed'
        - runtime interprets the effect text
        - runtime validates targets and conditions
        - runtime executes the effect or creates a pending choice
        """
        trigger_context = self.trigger_system.pop_next_trigger(self.state_store)
        trigger_spec = self.effect_interpreter.resolve_trigger(
            trigger_context=trigger_context,
            state=self.state_store,
            card_database=self.card_database,
        )

        validation_result = self.runtime_validator.validate_trigger(
            trigger_spec=trigger_spec,
            state=self.state_store,
            card_database=self.card_database,
        )

        if validation_result.status == "pending_choice":
            self.state_store.enqueue_pending_choice(validation_result.pending_choice)
            self.gameplay_logger.log_pending_choice(
                game_id=self.state_store.get_game_id(),
                choice=validation_result.pending_choice,
            )
            return

        if validation_result.status == "invalid":
            self.gameplay_logger.log_trigger_skipped(
                game_id=self.state_store.get_game_id(),
                trigger_context=trigger_context,
                reason=validation_result.reason,
            )
            return

        self.primitive_executor.execute_trigger(
            trigger_spec=trigger_spec,
            state=self.state_store,
        )
        self.gameplay_logger.log_trigger_resolved(
            game_id=self.state_store.get_game_id(),
            trigger_context=trigger_context,
            trigger_spec=trigger_spec,
        )

    def apply_rule_check(self):
        """
        Apply one automatic rule check.

        Example:
        - a Unit took fatal damage
        - rules management marks it destroyed
        - card moves to trash
        - any related trigger is registered
        """
        rule_event = self.rules_management.apply_next_rule(self.state_store)
        self.gameplay_logger.log_rule_event(
            game_id=self.state_store.get_game_id(),
            rule_event=rule_event,
        )

    def is_game_over(self):
        """
        Return True when the game has ended.
        """
        return self.rules_management.is_game_over(self.state_store)

    def get_winner(self):
        """
        Return the winning player id, or None.
        """
        return self.rules_management.get_winner(self.state_store)

    def has_pending_choice(self):
        """
        Return True when runtime is waiting for a player choice.
        """
        return self.state_store.peek_pending_choice() is not None

    def _resolve_pending_choice(self, parsed_command, pending_choice):
        """
        Resolve one opening or runtime choice.
        """
        if self.state_store.peek_pending_choice() is not pending_choice:
            raise ValueError("pending choice queue head changed before resolution")

        if pending_choice["type"] == "choose_turn_order":
            self._resolve_turn_order_choice(parsed_command, pending_choice)
            return

        if pending_choice["type"] == "mulligan":
            self._resolve_mulligan_choice(parsed_command, pending_choice)
            return

        raise ValueError(f"unknown pending choice type: {pending_choice['type']}")

    def _resolve_turn_order_choice(self, parsed_command, pending_choice):
        """
        Resolve the first/second choice.
        """
        decision_player = pending_choice["player_id"]
        choice_id = getattr(parsed_command, "choice_id", None)
        if choice_id not in {"go_first", "go_second"}:
            raise ValueError("turn order choice must be go_first or go_second")

        first_player = decision_player
        if choice_id == "go_second":
            first_player = self.state_store.get_other_player(decision_player)

        self.state_store.pop_pending_choice()
        self._set_turn_order(first_player)
        self.gameplay_logger.log_system_event(
            game_id=self.state_store.get_game_id(),
            event_type="choice_resolved",
            payload={
                "message": f"{decision_player} 選擇由 {first_player} 先攻。",
                "features": self.state_store.build_snapshot(),
            },
        )
        self._begin_opening_hands()

    def _resolve_mulligan_choice(self, parsed_command, pending_choice):
        """
        Resolve keep/redraw for one player.
        """
        player_id = pending_choice["player_id"]
        choice_id = getattr(parsed_command, "choice_id", None)
        if choice_id not in {"keep", "redraw"}:
            raise ValueError("mulligan choice must be keep or redraw")

        if choice_id == "redraw":
            self.state_store.return_hand_to_deck_for_mulligan(player_id)
            self.state_store.draw_cards(player_id, 5)

        self.state_store.mark_mulligan_done(player_id)
        self.state_store.pop_pending_choice()
        self.gameplay_logger.log_system_event(
            game_id=self.state_store.get_game_id(),
            event_type="mulligan_resolved",
            payload={
                "message": f"{player_id} 選擇{'重抽' if choice_id == 'redraw' else '保留'}起手牌。",
                "features": self.state_store.build_snapshot(),
            },
        )

        next_player = self.state_store.get_second_player()
        if player_id == self.state_store.get_first_player():
            next_player = self.state_store.get_second_player()
        else:
            next_player = None

        if next_player is not None:
            choice = {
                "type": "mulligan",
                "player_id": next_player,
                "message": "請決定是否保留起手牌",
                "options": [
                    {"id": "keep", "label": "保留"},
                    {"id": "redraw", "label": "重抽"},
                ],
            }
            self.state_store.enqueue_pending_choice(choice)
            self.gameplay_logger.log_pending_choice(
                game_id=self.state_store.get_game_id(),
                choice=choice,
            )
            self.state_store.save_snapshot()
            return

        self._finish_opening_setup()

    def _set_turn_order(self, first_player):
        """
        Persist first/second player selection into state.
        """
        second_player = self.state_store.get_other_player(first_player)
        self.state_store.set_first_player(first_player)
        self.state_store.set_second_player(second_player)
        self.state_store.set_active_player(first_player)
        self.state_store.set_priority_player(first_player)

    def _begin_opening_hands(self):
        """
        Draw opening hands and create the first mulligan choice.
        """
        self.state_store.shuffle_main_deck("P1")
        self.state_store.shuffle_main_deck("P2")
        self.state_store.draw_cards("P1", 5)
        self.state_store.draw_cards("P2", 5)
        first_player = self.state_store.get_first_player()
        choice = {
            "type": "mulligan",
            "player_id": first_player,
            "message": "請決定是否保留起手牌",
            "options": [
                {"id": "keep", "label": "保留"},
                {"id": "redraw", "label": "重抽"},
            ],
        }
        self.state_store.enqueue_pending_choice(choice)
        self.gameplay_logger.log_system_event(
            game_id=self.state_store.get_game_id(),
            event_type="game_started",
            payload={
                "message": f"先後攻已確定，{first_player} 為先攻，雙方已完成起手抽牌。",
                "first_player": first_player,
                "features": self.state_store.build_snapshot(),
            },
        )
        self.gameplay_logger.log_pending_choice(
            game_id=self.state_store.get_game_id(),
            choice=choice,
        )
        self.state_store.save_snapshot()

    def _finish_opening_setup(self):
        """
        Finalize pre-game setup after both mulligans are done.
        """
        self.state_store.place_shields("P1", 6)
        self.state_store.place_shields("P2", 6)
        self.state_store.set_ex_resource(self.state_store.get_second_player(), 1)
        self.state_store.set_turn(1)
        self.state_store.set_phase("main")
        self.state_store.set_step("start")
        self.gameplay_logger.log_system_event(
            game_id=self.state_store.get_game_id(),
            event_type="rule_event",
            payload={
                "message": "開局設置完成，進入主要階段。",
                "features": self.state_store.build_snapshot(),
            },
        )
        self.state_store.save_snapshot()


if __name__ == "__main__":
    # Pseudo bootstrap only.
    # Real wiring should provide concrete implementations.
    state_store = None
    card_database = None
    effect_interpreter = None
    runtime_validator = None
    primitive_executor = None
    rules_management = None
    trigger_system = None
    gameplay_logger = None

    runtime_core = RuntimeCore(
        state_store=state_store,
        card_database=card_database,
        effect_interpreter=effect_interpreter,
        runtime_validator=runtime_validator,
        primitive_executor=primitive_executor,
        rules_management=rules_management,
        trigger_system=trigger_system,
        gameplay_logger=gameplay_logger,
    )

    # Example:
    # game_id = runtime_core.start_game(first_player="P1")
    # print(game_id)
