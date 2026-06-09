"""
Lean pseudo class for the V2 simulator runner.

This file is intentionally simple.
It shows what the runner should own, and what it should delegate.
"""

import random


class SimulatorRunner:
    """
    Outer controller for one AI vs AI game.

    Responsibilities:
    - start a game
    - ask the correct AI for one command
    - pass the command to runtime
    - keep looping until the game ends

    Non-responsibilities:
    - do not interpret card text
    - do not validate card legality
    - do not mutate game state directly
    - do not resolve triggers directly
    """

    def __init__(
        self,
        state_store,
        viewer_state_builder,
        ai_player_client,
        command_parser,
        runtime_core,
        gameplay_logger,
        max_steps=200,
    ):
        self.state_store = state_store
        self.viewer_state_builder = viewer_state_builder
        self.ai_player_client = ai_player_client
        self.command_parser = command_parser
        self.runtime_core = runtime_core
        self.gameplay_logger = gameplay_logger

        self.max_steps = max_steps

        self.game_id = None
        self.step_count = 0
        self.finished = False
        self.winner = None

    def start_game(self, first_player=None, decision_player=None):
        """
        Create a new game and let runtime build the initial state.

        Opening flow:
        - choose which player gets to decide turn order
        - let AI answer the opening pending choice for first/second
        - let AI answer opening mulligan choices
        - stop when opening setup is complete
        """
        self._reset_runner_state()

        self.game_id = self.state_store.create_game_shell()
        self.gameplay_logger.open_game(self.game_id)
        self._start_opening_sequence(
            first_player=first_player,
            decision_player=decision_player,
        )
        return self.game_id

    def run(self, first_player=None, decision_player=None):
        """
        Main loop for one full game.
        """
        self.start_game(
            first_player=first_player,
            decision_player=decision_player,
        )
        while not self.finished and self.step_count < self.max_steps:
            self.step_once()

        return self.build_result()

    def step_once(self):
        """
        Advance the game by one outer-loop step.

        The runner first lets runtime auto-resolve anything that does not need
        player input. Only when runtime says a player decision is needed does
        the runner call AI.
        """
        self.step_count += 1

        self.runtime_core.advance_until_decision_or_stable()

        if self.runtime_core.is_game_over():
            self.finished = True
            self.winner = self.runtime_core.get_winner()
            return

        if self.state_store.peek_pending_choice() is not None:
            self.handle_pending_choice()
            return

        if self.state_store.needs_action_window():
            self.handle_player_action()
            return

        self.finished = True

    def handle_pending_choice(self):
        """
        Ask the choice owner to answer a pending choice.

        Example:
        - runtime says a card needs a target
        - runner builds viewer state
        - AI returns: choose choice_7 enemy_unit_2
        - runner parses and sends it back to runtime
        """
        pending_choice = self.state_store.peek_pending_choice()
        if pending_choice is None:
            raise RuntimeError("handle_pending_choice called without a pending choice")
        player_id = pending_choice["player_id"]
        viewer_state = self.viewer_state_builder.build(
            self.state_store,
            viewer_player=player_id,
        )
        raw_command = self.ai_player_client.decide(
            player_id=player_id,
            viewer_state=viewer_state,
        )
        parsed_command = self.command_parser.parse(raw_command, viewer_state)
        self.runtime_core.resolve_command(parsed_command)

    def handle_player_action(self):
        """
        Ask the current acting player for one normal action.

        Example:
        - P1 main phase
        - AI returns: play_card hand_3 target enemy_unit_2
        - runner parses and sends it to runtime
        """
        player_id = self.state_store.get_priority_player()
        viewer_state = self.viewer_state_builder.build(
            self.state_store,
            viewer_player=player_id,
        )
        raw_command = self.ai_player_client.decide(
            player_id=player_id,
            viewer_state=viewer_state,
        )
        parsed_command = self.command_parser.parse(raw_command, viewer_state)
        self.runtime_core.resolve_command(parsed_command)

    def _start_opening_sequence(self, first_player=None, decision_player=None):
        """
        Bootstrap the opening sequence before the normal game loop begins.

        Runner owns the orchestration only. Runtime still owns the real state
        transitions and should expose the opening setup via pending choices.
        """
        if decision_player is None and first_player is None:
            decision_player = random.choice(["P1", "P2"])

        self.runtime_core.start_opening_sequence(
            first_player=first_player,
            decision_player=decision_player,
        )
        self._resolve_opening_choices()

    def _resolve_opening_choices(self):
        """
        Let AI answer opening-only pending choices before the main loop starts.
        """
        opening_choice_types = {
            "choose_turn_order",
            "mulligan",
        }

        while True:
            pending_choice = self.state_store.peek_pending_choice()
            if pending_choice is None:
                break

            if pending_choice.get("type") not in opening_choice_types:
                break

            self.handle_pending_choice()
            self.runtime_core.advance_until_decision_or_stable()

    def _reset_runner_state(self):
        """
        Reset per-game runner flags before opening setup begins.
        """
        self.step_count = 0
        self.finished = False
        self.winner = None

    def build_result(self):
        """
        Return a small summary for the finished run.
        """
        return {
            "game_id": self.game_id,
            "finished": self.finished,
            "winner": self.winner,
            "step_count": self.step_count,
            "gameplay_log_path": self.gameplay_logger.get_path(self.game_id),
        }


def bootstrap_production_runner():
    """
    Placeholder bootstrap for production wiring.

    Keep the intended construction path visible without leaving unreachable code
    in the module entrypoint.
    """
    from gameplay_logger import GameplayLogger
    from runtime_core import RuntimeCore
    from state_store import StateStore
    from support.state_store_support import (
        CardDatabase,
        DeckConfig,
        GameplayYamlWriter,
        SnapshotWriter,
    )

    output_root = "/Users/hello/Desktop/cardAI/game-states"

    card_database = CardDatabase(
        card_data_root="/Users/hello/Desktop/cardAI/card/data",
    )
    deck_config = DeckConfig(
        deck_file="/Users/hello/Desktop/cardAI/card/gcgdecks.json",
    )
    snapshot_writer = SnapshotWriter(output_root)
    state_store = StateStore(
        card_database=card_database,
        deck_config=deck_config,
        snapshot_writer=snapshot_writer,
    )
    yaml_writer = GameplayYamlWriter(output_root)
    gameplay_logger = GameplayLogger(
        yaml_writer=yaml_writer,
        state_store=state_store,
    )

    class _PlaceholderComponent:
        def __getattr__(self, name):
            raise NotImplementedError(
                f"Provide a concrete implementation for '{name}' before using "
                "non-opening runtime paths."
            )

    runtime = RuntimeCore(
        state_store=state_store,
        card_database=card_database,
        effect_interpreter=_PlaceholderComponent(),
        runtime_validator=_PlaceholderComponent(),
        primitive_executor=_PlaceholderComponent(),
        rules_management=_PlaceholderComponent(),
        trigger_system=_PlaceholderComponent(),
        gameplay_logger=gameplay_logger,
    )

    return state_store, gameplay_logger, runtime


if __name__ == "__main__":
    state_store, gameplay_logger, runtime = bootstrap_production_runner()
    game_id = runtime.start_game()
