"""
Lean pseudo class for the V2 state store.

This file is intentionally simple.
It shows what state_store should own, and what it should delegate.
"""

import random
from datetime import datetime


class StateStore:
    """
    In-memory owner of the real game state.

    Responsibilities:
    - hold the current game state in memory
    - create the initial state for a new game
    - provide getters and setters for runtime
    - export the latest snapshot to gameState.yaml

    Non-responsibilities:
    - do not decide strategy
    - do not interpret card text
    - do not validate rules by itself
    - do not treat gameState.yaml as source of truth
    """

    def __init__(self, card_database, deck_config, snapshot_writer):
        self.card_database = card_database
        self.deck_config = deck_config
        self.snapshot_writer = snapshot_writer

        self.game_id = None
        self.state = None

    def create_game_shell(self, p1_deck_id="deck001", p2_deck_id="deck001"):
        """
        Build the opening shell before turn order and mulligan are resolved.
        """
        self.game_id = self._build_game_id()

        p1_deck = self.deck_config.get_deck(p1_deck_id)
        p2_deck = self.deck_config.get_deck(p2_deck_id)

        self.state = {
            "game_id": self.game_id,
            "turn": 0,
            "phase": "pre-game",
            "step": "opening",
            "active_player": None,
            "priority_player": None,
            "current_attacker": None,
            "pending_choice": [],
            "trigger_queue": [],
            "game_over": False,
            "winner": None,
            "opening": {
                "decision_player": None,
                "first_player": None,
                "second_player": None,
                "mulligan_done": {
                    "P1": False,
                    "P2": False,
                },
            },
            "players": {
                "P1": self._build_player_state("P1", p1_deck),
                "P2": self._build_player_state("P2", p2_deck),
            },
        }

        self.save_snapshot()
        return self.game_id

    def get_game_id(self):
        """
        Return the current game id.
        """
        return self.game_id

    def get_state(self):
        """
        Return the full in-memory state.
        """
        return self.state

    def get_player_state(self, player_id):
        """
        Return one player's state block.
        """
        return self.state["players"][player_id]

    def get_priority_player(self):
        """
        Return the player who currently has priority.
        """
        return self.state["priority_player"]

    def set_priority_player(self, player_id):
        """
        Update the current priority player.
        """
        self.state["priority_player"] = player_id

    def set_active_player(self, player_id):
        """
        Update the current active player.
        """
        self.state["active_player"] = player_id

    def set_turn(self, turn):
        """
        Update the current turn number.
        """
        self.state["turn"] = turn

    def set_phase(self, phase):
        """
        Update the current phase.
        """
        self.state["phase"] = phase

    def set_step(self, step):
        """
        Update the current step.
        """
        self.state["step"] = step

    def get_other_player(self, player_id):
        """
        Return the opposing player id.
        """
        return "P2" if player_id == "P1" else "P1"

    def choose_random_player(self):
        """
        Return one random player id.
        """
        return random.choice(["P1", "P2"])

    def set_decision_player(self, player_id):
        """
        Record which player may choose first/second.
        """
        self.state["opening"]["decision_player"] = player_id

    def set_first_player(self, player_id):
        """
        Record the chosen first player.
        """
        self.state["opening"]["first_player"] = player_id

    def set_second_player(self, player_id):
        """
        Record the chosen second player.
        """
        self.state["opening"]["second_player"] = player_id

    def get_first_player(self):
        """
        Return the chosen first player.
        """
        return self.state["opening"]["first_player"]

    def get_second_player(self):
        """
        Return the chosen second player.
        """
        return self.state["opening"]["second_player"]

    def shuffle_main_deck(self, player_id):
        """
        Shuffle one player's main deck in place.
        """
        random.shuffle(self.state["players"][player_id]["deck"])

    def draw_cards(self, player_id, count):
        """
        Draw count cards from main deck into hand.
        """
        player = self.state["players"][player_id]
        draw_count = min(count, len(player["deck"]))
        drawn = player["deck"][:draw_count]
        player["hand"].extend(drawn)
        del player["deck"][:draw_count]
        return drawn

    def return_hand_to_deck_for_mulligan(self, player_id):
        """
        Return hand to deck, shuffle, and empty hand for mulligan.
        """
        player = self.state["players"][player_id]
        player["deck"].extend(player["hand"])
        player["hand"] = []
        self.shuffle_main_deck(player_id)

    def mark_mulligan_done(self, player_id):
        """
        Mark one player's mulligan as finished.
        """
        self.state["opening"]["mulligan_done"][player_id] = True

    def is_mulligan_done(self, player_id):
        """
        Return True when one player's mulligan is finished.
        """
        return self.state["opening"]["mulligan_done"][player_id]

    def place_shields(self, player_id, count):
        """
        Move top count cards from deck into hidden shields.
        """
        player = self.state["players"][player_id]
        shield_count = min(count, len(player["deck"]))
        new_shields = player["deck"][:shield_count]
        player["shield"].extend(new_shields)
        del player["deck"][:shield_count]

    def set_ex_resource(self, player_id, amount):
        """
        Set the visible EX resource count for one player.
        """
        self.state["players"][player_id]["resources"]["ex"] = amount

    def peek_pending_choice(self):
        """
        Return the queue head pending choice, or None.
        """
        if not self.state["pending_choice"]:
            return None
        return self.state["pending_choice"][0]

    def list_pending_choices(self):
        """
        Return a shallow copy of the full pending choice queue.
        """
        return list(self.state["pending_choice"])

    def enqueue_pending_choice(self, choice):
        """
        Append one pending choice to the queue.

        Example:
        - runtime needs P1 to choose 1 enemy rested Unit
        - state_store keeps that choice until P1 answers
        """
        self.state["pending_choice"].append(choice)

    def pop_pending_choice(self):
        """
        Remove and return the current pending choice from the queue head.
        """
        if self.state["pending_choice"]:
            return self.state["pending_choice"].pop(0)
        return None

    def enqueue_trigger(self, trigger_event):
        """
        Add one trigger to the trigger queue.
        """
        self.state["trigger_queue"].append(trigger_event)

    def pop_next_trigger(self):
        """
        Pop the next trigger from the queue.
        """
        return self.state["trigger_queue"].pop(0)

    def has_trigger(self):
        """
        Return True when the trigger queue is not empty.
        """
        return len(self.state["trigger_queue"]) > 0

    def needs_action_window(self):
        """
        Return True when runtime is waiting for a normal player action.

        Example:
        - no pending choice
        - no pending trigger
        - phase is main or action window
        - game is not over
        """
        if self.state["game_over"]:
            return False
        if self.state["pending_choice"]:
            return False
        if self.state["trigger_queue"]:
            return False
        return self.state["phase"] in {"main", "action", "battle/action"}

    def mark_game_over(self, winner):
        """
        Mark the game as finished.
        """
        self.state["game_over"] = True
        self.state["winner"] = winner

    def save_snapshot(self):
        """
        Export the latest public-readable snapshot to gameState.yaml.

        gameState.yaml is not source of truth.
        It is only a rendered snapshot of the current memory state.
        """
        snapshot = self.build_snapshot()
        self.snapshot_writer.write_game_state(
            game_id=self.game_id,
            snapshot=snapshot,
        )

    def build_snapshot(self):
        """
        Build a serialized snapshot from the current memory state.

        Example:
        - keep turn, phase, priority, board, hand counts, resources, trash
        - omit hidden deck order and hidden shield identities
        """
        snapshot = {
            "game_id": self.state["game_id"],
            "turn": self.state["turn"],
            "phase": self.state["phase"],
            "step": self.state["step"],
            "active_player": self.state["active_player"],
            "priority_player": self.state["priority_player"],
            "current_attacker": self.state["current_attacker"],
            "pending_choice": self.list_pending_choices(),
            "game_over": self.state["game_over"],
            "winner": self.state["winner"],
            "p1": self._build_public_player_snapshot("P1"),
            "p2": self._build_public_player_snapshot("P2"),
        }
        if "opening" in self.state:
            snapshot["opening"] = {
                "decision_player": self.state["opening"]["decision_player"],
                "first_player": self.state["opening"]["first_player"],
                "second_player": self.state["opening"]["second_player"],
                "mulligan_done": dict(self.state["opening"]["mulligan_done"]),
            }
        return snapshot

    def _build_public_player_snapshot(self, player_id):
        """
        Build one player's public-safe snapshot block.
        """
        player = self.state["players"][player_id]
        return {
            "hand_count": len(player["hand"]),
            "deck_count": len(player["deck"]),
            "resource_deck_count": len(player["resource_deck"]),
            "shields": len(player["shield"]),
            "resources": player["resources"],
            "base": player["base"],
            "board": {
                "units": sum(1 for slot in player["battle_area"] if slot["unit_id"] is not None),
                "empty_slots": sum(1 for slot in player["battle_area"] if slot["unit_id"] is None),
                "rested_units": sum(1 for slot in player["battle_area"] if slot["status"] == "rested"),
                "damaged_units": sum(1 for slot in player["battle_area"] if slot["damage"] > 0),
                "blockers": sum(1 for slot in player["battle_area"] if "Blocker" in slot["keywords"]),
                "slots": player["battle_area"],
            },
            "trash": player["trash"],
            "removal": player["removal"],
        }

    def _build_player_state(self, player_id, deck_bundle):
        """
        Build one player's initial state block.
        """
        return {
            "player_id": player_id,
            "deck": list(deck_bundle["main_deck"]),
            "hand": [],
            "shield": [],
            "resource_deck": list(deck_bundle["resource_deck"]),
            "resources": {
                "active": 0,
                "rested": 0,
                "ex": 0,
            },
            "base": {
                "card_id": "EX-BASE",
                "ap": 0,
                "hp": 3,
                "damage": 0,
                "alive": True,
                "status": None,
            },
            "battle_area": [self._build_empty_slot(slot) for slot in range(6)],
            "trash": [],
            "removal": [],
        }

    def _build_empty_slot(self, slot):
        """
        Build one empty battle area slot.
        """
        return {
            "slot": slot,
            "unit_id": None,
            "pilot_id": None,
            "ap": 0,
            "hp": 0,
            "damage": 0,
            "status": None,
            "keywords": [],
            "link": False,
            "turns_on_field": 0,
        }

    def _build_game_id(self):
        """
        Return a new game id.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"game_{timestamp}"


if __name__ == "__main__":
    # Pseudo bootstrap only.
    # Real wiring should provide concrete implementations.
    card_database = None
    deck_config = None
    snapshot_writer = None

    state_store = StateStore(
        card_database=card_database,
        deck_config=deck_config,
        snapshot_writer=snapshot_writer,
    )

    # Example:
    # game_id = state_store.create_game_shell()
    # print(game_id)
