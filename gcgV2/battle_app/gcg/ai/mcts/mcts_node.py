"""MCTS tree node."""

from __future__ import annotations

from math import log, sqrt


class MctsNode:
    def __init__(self, action=None, parent=None, player_to_move=None):
        self.action = action
        self.parent = parent
        self.player_to_move = player_to_move
        self.children = {}
        self.visits = 0
        self.value = 0.0

    def available_children(self, legal_actions):
        legal = set(legal_actions)
        return [child for action, child in self.children.items() if action in legal]

    def untried_actions(self, legal_actions):
        return [action for action in legal_actions if action not in self.children]

    def add_child(self, action, player_to_move=None):
        child = MctsNode(action=action, parent=self, player_to_move=player_to_move)
        self.children[action] = child
        return child

    def best_ucb_child(self, legal_actions, exploration, observer_id):
        candidates = self.available_children(legal_actions)
        if not candidates:
            return None
        for child in candidates:
            if child.visits == 0:
                return child
        parent_visits = max(1, self.visits)
        perspective = 1.0 if self.player_to_move in {None, observer_id} else -1.0
        return max(
            candidates,
            key=lambda child: perspective * (child.value / child.visits)
            + exploration * sqrt(log(parent_visits) / child.visits),
        )

    def most_visited_child(self):
        if not self.children:
            return None
        return max(self.children.values(), key=lambda child: child.visits)
