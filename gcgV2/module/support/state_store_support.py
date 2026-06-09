"""
Production-oriented support helpers for state storage and log writing.

These adapters are intentionally lean:
- card metadata loading
- deck configuration loading
- public snapshot writing
- gameplay log writing
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - fallback keeps local bootstrap usable.
    yaml = None


if yaml is not None:
    class _NoAliasSafeDumper(yaml.SafeDumper):
        def ignore_aliases(self, data):
            return True


class CardDatabase:
    def __init__(self, card_data_root):
        self.card_data_root = Path(card_data_root)
        self.cards = self._load_cards()

    def get(self, card_id):
        return self.cards.get(card_id)

    def _load_cards(self):
        cards = {}
        for path in sorted(self.card_data_root.glob("*Card.json")):
            payload = json.loads(path.read_text())
            for card in payload.get("cards", {}).values():
                cards[card["id"]] = {
                    "id": card["id"],
                    "name": card.get("name"),
                    "cardType": card.get("cardType"),
                    "color": card.get("color"),
                    "level": card.get("level", 0),
                    "cost": card.get("cost", 0),
                    "ap": card.get("ap", 0),
                    "hp": card.get("hp", 0),
                    "zone": list(card.get("zone", [])),
                    "traits": list(card.get("traits", [])),
                    "link": list(card.get("link", [])),
                    "effects": {
                        "description": list(
                            card.get("effects", {}).get("description", [])
                        ),
                    },
                }
        return cards


class DeckConfig:
    def __init__(self, deck_file):
        self.deck_file = Path(deck_file)
        payload = json.loads(self.deck_file.read_text())
        self.decks = payload["decks"]

    def get_deck(self, deck_id):
        deck = self._get_deck_record(deck_id)
        cards = deck.get("cards")
        if cards is None:
            raise KeyError(
                f"Deck '{deck_id}' is missing 'cards' in {self.deck_file}."
            )
        if not isinstance(cards, list):
            raise TypeError(
                f"Deck '{deck_id}' field 'cards' must be a list in {self.deck_file}."
            )
        resource_deck = deck.get("resource_deck")
        if resource_deck is None:
            raise KeyError(
                f"Deck '{deck_id}' is missing 'resource_deck' in {self.deck_file}."
            )
        if not isinstance(resource_deck, list):
            raise TypeError(
                f"Deck '{deck_id}' field 'resource_deck' must be a list in "
                f"{self.deck_file}."
            )
        return {
            "deck_id": deck_id,
            "main_deck": list(cards),
            "resource_deck": list(resource_deck),
        }

    def _get_deck_record(self, deck_id):
        deck = self.decks.get(deck_id)
        if deck is None:
            raise KeyError(
                f"Deck '{deck_id}' is missing from {self.deck_file}."
            )
        return deck


class SnapshotWriter:
    def __init__(self, output_root):
        self.output_root = Path(output_root)

    def write_game_state(self, game_id, snapshot):
        path = _ensure_game_dir(self.output_root, game_id) / "gameState.yaml"
        path.write_text(_serialize_yaml(snapshot))


class GameplayYamlWriter:
    def __init__(self, output_root):
        self.output_root = Path(output_root)

    def create_gameplay_log(self, game_id, schema_version):
        payload = {
            "schema_version": schema_version,
            "game_id": game_id,
            "summary": {
                "status": "in_progress",
                "winner": None,
                "turn": 0,
                "phase": "pre-game",
                "total_events": 0,
            },
            "events": [],
        }
        self._write(game_id, payload)

    def append_event(self, game_id, event):
        payload = self._read(game_id)
        payload["events"].append(event)
        payload["summary"]["turn"] = event.get("turn")
        payload["summary"]["phase"] = event.get("phase")
        payload["summary"]["total_events"] = len(payload["events"])
        self._write(game_id, payload)

    def get_gameplay_path(self, game_id):
        return str(self.output_root / game_id / "gamePlay.yaml")

    def _read(self, game_id):
        path = _ensure_game_dir(self.output_root, game_id) / "gamePlay.yaml"
        return _deserialize_yaml(path.read_text())

    def _write(self, game_id, payload):
        path = _ensure_game_dir(self.output_root, game_id) / "gamePlay.yaml"
        path.write_text(_serialize_yaml(payload))


def _serialize_yaml(payload):
    if yaml is not None:
        return yaml.dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            Dumper=_NoAliasSafeDumper,
        )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _deserialize_yaml(text):
    if yaml is not None:
        return yaml.safe_load(text)
    return json.loads(text)


def _ensure_game_dir(output_root, game_id):
    game_dir = Path(output_root) / game_id
    game_dir.mkdir(parents=True, exist_ok=True)
    return game_dir
