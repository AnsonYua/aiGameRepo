"""Card metadata and deck configuration loading."""

from __future__ import annotations

import json
from pathlib import Path

from . import config


class CardDatabase:
    """Read-only card metadata index keyed by card id（不含 set 前綴）。"""

    def __init__(self, card_data_root=None):
        self.card_data_root = Path(card_data_root or config.card_data_root())
        self.cards = self._load_cards()

    def get(self, card_id):
        if card_id is None:
            return None
        card = self.cards.get(card_id)
        if card is not None:
            return card
        normalized = self.normalize_id(card_id)
        if normalized is None:
            return None
        return self.cards.get(normalized)

    @staticmethod
    def normalize_id(card_id):
        if not isinstance(card_id, str):
            return None
        if "/" in card_id:
            return card_id.split("/")[-1].strip() or None
        return card_id.strip() or None

    def effect_texts(self, card_id):
        card = self.get(card_id)
        if card is None:
            return []
        return list(card.get("effects", {}).get("description", []))

    def effect_rules(self, card_id):
        card = self.get(card_id)
        if card is None:
            return []
        return list(card.get("effects", {}).get("rules", []))

    def _load_cards(self):
        cards = {}
        for path in sorted(self.card_data_root.glob("*Card.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
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
                        "description": list(card.get("effects", {}).get("description", [])),
                        "rules": list(card.get("effects", {}).get("rules", [])),
                    },
                }
        return cards


class DeckConfig:
    """Deck list loader.

    歷史格式說明：deck json 的 ``resource_deck`` 欄位實際上放的是 token 卡
    （例如 st01/T-001）。GCG 正式規則的資源牌組是固定 10 張同質資源，
    因此這裡把該欄位解讀為 ``tokens``，資源牌組以張數表示。
    """

    def __init__(self, deck_file=None):
        self.deck_file = Path(deck_file or config.deck_file())
        payload = json.loads(self.deck_file.read_text(encoding="utf-8"))
        self.decks = payload["decks"]

    def get_deck(self, deck_id):
        deck = self.decks.get(deck_id)
        if deck is None:
            raise KeyError(f"Deck '{deck_id}' is missing from {self.deck_file}.")
        cards = deck.get("cards")
        if not isinstance(cards, list) or not cards:
            raise ValueError(f"Deck '{deck_id}' field 'cards' must be a non-empty list.")
        tokens = deck.get("tokens", deck.get("resource_deck", []))
        if not isinstance(tokens, list):
            raise ValueError(f"Deck '{deck_id}' field 'tokens' must be a list.")
        return {
            "deck_id": deck_id,
            "main_deck": list(cards),
            "resource_deck_size": int(deck.get("resource_deck_size", config.RESOURCE_DECK_SIZE)),
            "tokens": list(tokens),
        }
