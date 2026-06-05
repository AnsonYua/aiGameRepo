import json
import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
CARD_DATA_DIR = PROJECT_ROOT / "card" / "data"
DECKS_FILE = PROJECT_ROOT / "card" / "gcgdecks.json"

_card_cache: dict[str, dict] = {}
_loaded = False


def _load_all_cards():
    global _loaded
    if _loaded:
        return
    for f in sorted(CARD_DATA_DIR.glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
        for card_id, card in data.get("cards", {}).items():
            set_prefix = f.stem.replace("Card", "")
            full_id = f"{set_prefix}/{card_id}"
            _card_cache[full_id] = card
    _loaded = True


def get_card(card_id: str) -> Optional[dict]:
    _load_all_cards()
    return _card_cache.get(card_id)


def get_card_name(card_id: str) -> str:
    card = get_card(card_id)
    if card:
        return card.get("name", card_id)
    return card_id


def get_card_type(card_id: str) -> str:
    card = get_card(card_id)
    if card:
        return card.get("cardType", "unknown")
    return "unknown"


def get_card_level(card_id: str) -> int:
    card = get_card(card_id)
    if card:
        return card.get("level", 0)
    return 0


def get_card_cost(card_id: str) -> int:
    card = get_card(card_id)
    if card:
        return card.get("cost", 0)
    return 0


def get_card_ap(card_id: str) -> int:
    card = get_card(card_id)
    if card:
        return card.get("ap", 0)
    return 0


def get_card_hp(card_id: str) -> int:
    card = get_card(card_id)
    if card:
        return card.get("hp", 0)
    return 0


def get_card_keywords(card_id: str) -> list[str]:
    card = get_card(card_id)
    if not card:
        return []
    keywords = []
    effects = card.get("effects", {})
    if isinstance(effects, dict):
        rules = effects.get("rules", [])
        for rule in rules:
            action = rule.get("action", "")
            if action in ("block", "firstStrike", "breach", "deploy", "burst"):
                keywords.append(action)
            eid = rule.get("effectId", "")
            if "first_strike" in eid.lower():
                keywords.append("First Strike")
            if "blocker" in eid.lower() or action == "block":
                keywords.append("Blocker")
            if "breach" in eid.lower():
                keywords.append("Breach")
            if "burst" in eid.lower():
                keywords.append("Burst")
    link_names = card.get("link", [])
    if link_names:
        keywords.append(f"Link: {', '.join(link_names)}")
    return keywords


def get_deck(player_id: str) -> list[str]:
    with open(DECKS_FILE) as fh:
        decks = json.load(fh)
    player_deck = decks.get("playerDecks", {}).get(player_id, {})
    active_deck = player_deck.get("activeDeck", "")
    deck_cards = decks.get("decks", {}).get(active_deck, {}).get("cards", [])
    return list(deck_cards)


def build_card_summary(card_id: str) -> dict:
    card = get_card(card_id)
    if not card:
        return {"card_id": card_id, "name": card_id}
    link = card.get("link", [])
    link_suffix = f" [Link: {', '.join(link)}]" if link else ""
    keywords = get_card_keywords(card_id)
    kw_filtered = [k for k in keywords if not k.startswith("Link:")]
    kw_suffix = f" | {' '.join(kw_filtered)}" if kw_filtered else ""
    return {
        "card_id": card_id,
        "name": card.get("name", card_id),
        "cardType": card.get("cardType", "unknown"),
        "level": card.get("level", 0),
        "cost": card.get("cost", 0),
        "ap": card.get("ap", 0),
        "hp": card.get("hp", 0),
        "color": card.get("color", ""),
        "link": link,
        "keywords": keywords,
        "display": f"{card_id} | {card.get('name', card_id)} | {card.get('cardType', '?')} | Lv{card.get('level', 0)} | Cost:{card.get('cost', 0)} | AP:{card.get('ap', 0)}/HP:{card.get('hp', 0)}{link_suffix}{kw_suffix}"
    }
