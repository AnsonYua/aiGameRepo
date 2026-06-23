"""AI vs AI simulator orchestration（薄層，只負責 loop 與接線）。"""

from __future__ import annotations

import logging

from ..engine.command_parser import CommandParser


logger = logging.getLogger(__name__)


class SimulatorError(RuntimeError):
    def __init__(self, message, classification):
        super().__init__(message)
        self.classification = classification


class SimulatorRunner:
    def __init__(
        self,
        runtime,
        state_store,
        action_enumerator,
        viewer_builder,
        prompt_builder,
        players,
        gameplay_logger,
        ai_trace_writer=None,
        command_parser=None,
        max_steps=400,
    ):
        self.runtime = runtime
        self.state = state_store
        self.enumerator = action_enumerator
        self.viewer_builder = viewer_builder
        self.prompt_builder = prompt_builder
        self.players = players
        self.gameplay_logger = gameplay_logger
        self.ai_trace_writer = ai_trace_writer
        self.parser = command_parser or CommandParser()
        self.max_steps = max_steps

        self.game_id = None
        self.step_count = 0
        self.status = "not_started"

    def start_game(self, first_player=None, decision_player=None):
        self.step_count = 0
        self.game_id = self.state.create_game_shell()
        self.gameplay_logger.open_game(self.game_id)
        self.runtime.start_opening_sequence(
            first_player=first_player, decision_player=decision_player,
        )
        self.status = "in_progress"
        return self.game_id

    def run(self):
        try:
            self._loop()
        except SimulatorError as exc:
            self.status = f"incomplete:{exc.classification}"
            logger.error("simulation aborted: %s (%s)", exc, exc.classification)
        finally:
            self._finalize()
        return self.build_result()

    def _loop(self):
        while self.step_count < self.max_steps:
            self.runtime.advance_until_decision_or_stable()
            if self.runtime.is_game_over():
                self.status = "finished"
                return
            self.step_count += 1

            pending_choice = self.state.peek_pending_choice()
            if pending_choice is not None:
                actor = pending_choice["player_id"]
                legal_commands = self.enumerator.pending_choice_commands(pending_choice)
            elif self.state.needs_action_window():
                actor = self.state.get_priority_player()
                legal_commands = self.enumerator.legal_commands(actor)
            else:
                raise SimulatorError(
                    f"runtime stalled at phase={self.state.get_phase()} step={self.state.get_step()}",
                    classification="runtime_problem",
                )

            if not legal_commands:
                raise SimulatorError(
                    f"no legal commands for {actor} at phase={self.state.get_phase()}",
                    classification="runtime_problem",
                )
            self._decide_and_resolve(actor, legal_commands, pending_choice)

        if not self.runtime.is_game_over():
            self.status = "incomplete:max_steps"

    def _decide_and_resolve(self, actor, legal_commands, pending_choice, retry_note=None):
        viewer_bundle = self.viewer_builder.build_for_player(self.state, actor)
        prompt_payload = self.prompt_builder.build(viewer_bundle, legal_commands)
        if retry_note:
            prompt_payload["error_feedback"] = retry_note
        raw_command = self.players[actor].decide(self.game_id, actor, prompt_payload)
        logger.info("decision game=%s player=%s command=%s", self.game_id, actor, raw_command)

        try:
            parsed = self.parser.parse(raw_command, actor)
            normalized = parsed.command_line()
            if normalized not in set(legal_commands):
                raise ValueError(
                    f"指令不在合法清單中：{normalized}；合法選項：{legal_commands}"
                )
            if pending_choice is not None:
                self.runtime.resolve_pending_choice(parsed, pending_choice)
            else:
                self.runtime.resolve_command(parsed)
        except ValueError as exc:
            self.gameplay_logger.log_invalid_command(
                game_id=self.game_id,
                player_id=actor,
                raw_command=raw_command,
                reason=str(exc),
            )
            if retry_note is not None:
                raise SimulatorError(
                    f"{actor} 連續輸出不合法指令：{exc}",
                    classification="ai_decision_problem",
                ) from exc
            # 帶錯誤訊息重問一次（有上限）
            self._decide_and_resolve(
                actor, legal_commands, pending_choice,
                retry_note=f"你上一個指令不合法：{exc}。請從 legal_commands 重新選擇。",
            )

    def _finalize(self):
        winner = self.runtime.get_winner()
        win_reason = self.state.get_state().get("win_reason")
        status = self.status if self.status != "in_progress" else "incomplete:unknown"
        self.gameplay_logger.close_game(
            game_id=self.game_id,
            status=status,
            winner=winner,
            win_reason=win_reason,
        )
        self.state.save_snapshot()

    def build_result(self):
        return {
            "game_id": self.game_id,
            "status": self.status,
            "winner": self.runtime.get_winner(),
            "win_reason": self.state.get_state().get("win_reason"),
            "turn": self.state.get_turn(),
            "step_count": self.step_count,
            "gameplay_log_path": self.gameplay_logger.get_path(self.game_id),
            "ai_trace_path": (
                self.ai_trace_writer.get_trace_path(self.game_id)
                if self.ai_trace_writer is not None else None
            ),
        }
