"""Player adapter exposing heuristic ISMCTS through the simulator contract."""

from __future__ import annotations

import logging
import random

from .ismcts import IsmctsSearch
from .heuristics import choose_rollout_action
from .simulation import SimulationEngine


logger = logging.getLogger(__name__)


class MctsPlayer:
    def __init__(
        self,
        card_database,
        deck_config,
        rules_index,
        iterations=200,
        exploration_constant=1.4,
        max_rollout_depth=20,
        epsilon=0.15,
        time_budget_ms=5000,
        deck_id=None,
        rng=None,
    ):
        self.rng = rng or random
        self.simulation = SimulationEngine(card_database, rules_index, rng=self.rng)
        self.search_engine = IsmctsSearch(
            card_database=card_database,
            deck_config=deck_config,
            rules_index=rules_index,
            simulation_engine=self.simulation,
            iterations=iterations,
            exploration_constant=exploration_constant,
            max_rollout_depth=max_rollout_depth,
            epsilon=epsilon,
            time_budget_ms=time_budget_ms,
            deck_id=deck_id,
            rng=self.rng,
        )

    def decide(self, game_id, player_id, prompt_payload):
        legal_commands = list(prompt_payload.get("legal_commands") or [])
        if not legal_commands:
            raise RuntimeError("MCTS player got empty legal_commands")

        if all(command.startswith("choose ") for command in legal_commands):
            command = self._choose_pending(legal_commands)
            return f"CONSIDER: MCTS 使用簡單啟發式回應選擇。\nCOMMAND: {command}"

        if len(legal_commands) == 1:
            return f"CONSIDER: 只有一個合法指令，直接執行。\nCOMMAND: {legal_commands[0]}"

        viewer_state = prompt_payload.get("viewer_state")
        if not viewer_state:
            return f"CONSIDER: 缺少可見狀態，改選第一個合法指令。\nCOMMAND: {legal_commands[0]}"

        if self._is_existing_action_window(viewer_state):
            command = choose_rollout_action(
                legal_commands, self._viewer_state_as_score_state(viewer_state), player_id,
                self.search_engine.cards, self.rng, epsilon=0.0,
            ) or legal_commands[0]
            return f"CONSIDER: Action Step 缺少連續讓過資訊，保守選擇公開合法指令。\nCOMMAND: {command}"

        try:
            command = self.search_engine.search(viewer_state, player_id, legal_commands)
        except Exception as exc:
            logger.warning(
                "MCTS search failed game=%s player=%s error=%s",
                game_id,
                player_id,
                exc,
                exc_info=True,
            )
            command = legal_commands[0]
            return f"CONSIDER: MCTS 模擬失敗，改選第一個合法指令以維持對局進行。\nCOMMAND: {command}"
        if command not in legal_commands:
            command = legal_commands[0]
        iterations = self.search_engine.last_iterations
        return f"CONSIDER: MCTS 完成 {iterations} 次公開資訊模擬後選擇此合法指令。\nCOMMAND: {command}"

    def _choose_pending(self, legal_commands):
        for preferred in ("choose keep", "choose go_first", "choose activate"):
            if preferred in legal_commands:
                return preferred
        return legal_commands[0]

    def _is_existing_action_window(self, viewer_state):
        return (
            (viewer_state.get("phase") == "battle" and viewer_state.get("step") == "action")
            or (viewer_state.get("phase") == "end" and viewer_state.get("step") == "action")
        )

    def _viewer_state_as_score_state(self, viewer_state):
        players = {}
        for player_id, block in (viewer_state.get("players") or {}).items():
            players[player_id] = {"battle_area": list(block.get("battle_area") or [])}
        return {"players": players}
