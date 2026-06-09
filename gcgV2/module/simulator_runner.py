"""
Lean pseudo class for the V2 simulator runner.

This file is intentionally simple.
It shows what the runner should own, and what it should delegate.
"""

import random


class _NotReadyComponent:
    def __getattr__(self, name):
        raise NotImplementedError(
            f"Provide a concrete implementation for '{name}' before using "
            "non-opening runtime paths."
        )


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
        self.ensure_ai_ready_for_game()
        self._start_opening_sequence(
            first_player=first_player,
            decision_player=decision_player,
        )
        return self.game_id

    def prepare_next_step(self):
        """
        Advance runtime-owned automatic work only when no player decision is
        currently needed.
        """
        if self.state_store.get_state().get("game_over"):
            return

        if self.state_store.peek_pending_choice() is not None:
            return

        if self.state_store.needs_action_window():
            return

        self.runtime_core.advance_until_decision_or_stable()

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
        viewer_bundle = self.viewer_state_builder.build_for_player(
            self.state_store,
            viewer_player=player_id,
        )
        raw_command = self.ai_player_client.decide(
            game_id=self.game_id,
            player_id=player_id,
            viewer_bundle=viewer_bundle,
        )
        parsed_command = self.command_parser.parse(raw_command, viewer_bundle)
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
        viewer_bundle = self.viewer_state_builder.build_for_player(
            self.state_store,
            viewer_player=player_id,
        )
        raw_command = self.ai_player_client.decide(
            game_id=self.game_id,
            player_id=player_id,
            viewer_bundle=viewer_bundle,
        )
        parsed_command = self.command_parser.parse(raw_command, viewer_bundle)
        self.runtime_core.resolve_command(parsed_command)

    def ensure_ai_ready_for_game(self):
        """
        Ensure player-isolated AI sessions exist before the first choice.

        Opening pending choices like choose_turn_order should not pay session
        creation cost on the critical path.
        """
        if self.game_id is None:
            return

        self.ai_player_client.ensure_player_session(
            game_id=self.game_id,
            player_id="P1",
        )
        self.ai_player_client.ensure_player_session(
            game_id=self.game_id,
            player_id="P2",
        )

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

    def sync_finish_state(self):
        """
        Sync runner-level finish flags from the current runtime state.
        """
        current_state = self.state_store.get_state()
        if current_state.get("game_over"):
            self.finished = True
            self.winner = current_state.get("winner")

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

    runtime = RuntimeCore(
        state_store=state_store,
        card_database=card_database,
        effect_interpreter=_NotReadyComponent(),
        runtime_validator=_NotReadyComponent(),
        primitive_executor=_NotReadyComponent(),
        rules_management=_NotReadyComponent(),
        trigger_system=_NotReadyComponent(),
        gameplay_logger=gameplay_logger,
    )

    return state_store, gameplay_logger, runtime


class SimulatorLoopRunner:
    """
    Simulator loop runner for one full AI-vs-AI outer loop.

    It owns the top-level control flow:
    - advance runtime-owned automatic work
    - detect which kind of decision is needed
    - route pending choices and action windows to the correct AI
    - stop on stable terminal state or step limit
    """

    def __init__(self, simulator_runner):
        self.simulator_runner = simulator_runner
        self.viewer_bundle = None

    def _resolve_viewer_player(self):
        """
        Prefer the player who should see the latest decision-facing state.
        """
        pending_choice = self.simulator_runner.state_store.peek_pending_choice()
        if pending_choice is not None:
            return pending_choice["player_id"]

        priority_player = self.simulator_runner.state_store.get_priority_player()
        if priority_player is not None:
            return priority_player

        state_store = self.simulator_runner.state_store

        opening_state = state_store.get_state().get("opening", {})
        decision_player = opening_state.get("decision_player")
        if decision_player is not None:
            return decision_player

        return "P1"

    def run(self, viewer_player=None):
        """
        Run the outer simulator loop until the game finishes or hits step
        limit, then expose the final viewer bundle.
        """
        while (
            not self.simulator_runner.finished
            and self.simulator_runner.step_count < self.simulator_runner.max_steps
        ):
            self.simulator_runner.step_count += 1
            self.simulator_runner.prepare_next_step()
            self.simulator_runner.sync_finish_state()

            if self.simulator_runner.finished:
                break

            if self.simulator_runner.state_store.peek_pending_choice() is not None:
                self.simulator_runner.handle_pending_choice()
                continue

            if self.simulator_runner.state_store.needs_action_window():
                self.simulator_runner.handle_player_action()
                continue

            self.simulator_runner.finished = True
            break

        self.simulator_runner.sync_finish_state()

        if viewer_player is None:
            viewer_player = self._resolve_viewer_player()

        self.viewer_bundle = self.simulator_runner.viewer_state_builder.build_for_player(
            state_store=self.simulator_runner.state_store,
            viewer_player=viewer_player,
        )
        return {
            "result": self.simulator_runner.build_result(),
            "viewer_bundle": self.viewer_bundle,
        }


if __name__ == "__main__":
    from ai_player_client import AiPlayerClient
    from simple_command_parser import SimpleCommandParser
    from viewer_state_builder import ViewerStateBuilder

    state_store, gameplay_logger, runtime = bootstrap_production_runner()
    viewer_state_builder = ViewerStateBuilder()
    ai_player_client = AiPlayerClient()
    command_parser = SimpleCommandParser()
    simulator_runner = SimulatorRunner(
        state_store=state_store,
        viewer_state_builder=viewer_state_builder,
        ai_player_client=ai_player_client,
        command_parser=command_parser,
        runtime_core=runtime,
        gameplay_logger=gameplay_logger,
    )
    simulator_runner.start_game()
    simulator_loop_runner = SimulatorLoopRunner(
        simulator_runner=simulator_runner,
    )
    simulator_loop_runner.run()
