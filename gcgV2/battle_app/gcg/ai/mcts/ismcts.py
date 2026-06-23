"""Single-observer ISMCTS search."""

from __future__ import annotations

from copy import deepcopy
import random
import time

from .determinization import determinize_for_observer
from .heuristics import choose_rollout_action, evaluate
from .mcts_node import MctsNode


class IsmctsSearch:
    def __init__(
        self,
        card_database,
        deck_config,
        rules_index,
        simulation_engine,
        iterations=200,
        exploration_constant=1.4,
        max_rollout_depth=20,
        epsilon=0.15,
        time_budget_ms=5000,
        deck_id=None,
        rng=None,
    ):
        self.cards = card_database
        self.deck_config = deck_config
        self.rules = rules_index
        self.sim = simulation_engine
        self.iterations = iterations
        self.exploration = exploration_constant
        self.max_rollout_depth = max_rollout_depth
        self.epsilon = epsilon
        self.time_budget_ms = time_budget_ms
        self.deck_id = deck_id or {"P1": "deck001", "P2": "deck001"}
        self.rng = rng or random.Random()
        self.last_iterations = 0

    def search(self, viewer_state, observer_id, root_actions):
        root = MctsNode(player_to_move=observer_id)
        deadline = time.monotonic() + self.time_budget_ms / 1000.0
        self.last_iterations = 0
        for _ in range(max(1, self.iterations)):
            if time.monotonic() >= deadline:
                break
            state = determinize_for_observer(
                viewer_state, self.deck_config, observer_id, rng=self.rng, deck_id=self.deck_id,
            )
            self.sim.advance_until_decision(state)
            if time.monotonic() >= deadline:
                break
            node = root

            while True:
                if time.monotonic() >= deadline:
                    break
                legal = root_actions if node is root else self._legal_for_state(state)
                if not legal or state.get("game_over"):
                    break
                untried = node.untried_actions(legal)
                if untried:
                    self.rng.shuffle(untried)
                    expanded = False
                    for action in untried:
                        if self.sim.apply_action(state, state.get("priority_player"), action):
                            node = node.add_child(action, player_to_move=state.get("priority_player"))
                            expanded = True
                            break
                    if not expanded:
                        break
                    break
                child = node.best_ucb_child(legal, self.exploration, observer_id)
                if child is None:
                    break
                if not self.sim.apply_action(state, state.get("priority_player"), child.action):
                    break
                node = child

            result = evaluate(state, observer_id) if time.monotonic() >= deadline else self._rollout(state, observer_id, deadline)
            self._backpropagate(node, result)
            self.last_iterations += 1

        best = root.most_visited_child()
        if best is None:
            return root_actions[0]
        return best.action

    def _rollout(self, state, observer_id, deadline):
        state = deepcopy(state)
        for _ in range(max(0, self.max_rollout_depth)):
            if time.monotonic() >= deadline or state.get("game_over"):
                break
            self.sim.advance_until_decision(state)
            player_id = state.get("priority_player")
            legal = self._legal_for_state(state)
            if not player_id or not legal:
                break
            action = choose_rollout_action(legal, state, player_id, self.cards, self.rng, self.epsilon)
            if action is None:
                break
            if not self.sim.apply_action(state, player_id, action):
                break
        return evaluate(state, observer_id)

    def _legal_for_state(self, state):
        player_id = state.get("priority_player")
        if not player_id:
            return []
        return self.sim.legal_actions(state, player_id)

    def _backpropagate(self, node, result):
        while node is not None:
            node.visits += 1
            node.value += result
            node = node.parent
