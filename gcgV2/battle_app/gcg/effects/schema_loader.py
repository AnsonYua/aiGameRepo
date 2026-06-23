"""Load structured card effect schemas for deterministic runtime mode."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import config


class SchemaLoadError(ValueError):
    """Structured card effect schema is malformed."""


_RUNTIME_TIMING_BY_SCHEMA = {
    "BURST": "BURST_CONDITION",
    "ON_ATTACK": "ATTACK_PHASE",
    "ON_BOARD": "PAIRING_COMPLETE",
    "MAIN": "MAIN",
    "ACTION": "ACTION",
    "ENTERS_PLAY": "ENTERS_PLAY",
    "PAIRING_COMPLETE": "PAIRING_COMPLETE",
    "DESTROYED": "DESTROYED",
    "END_OF_TURN": "END_OF_TURN",
    "ON_BATTLE_DESTROY": "BATTLE_DESTROY",
    "ON_SHIELD_BREAK": "ON_SHIELD_BREAK",
    "ON_RESONANCE": "ON_RESONANCE",
}

_KEYWORD_BY_SCHEMA = {
    "BLOCKER": "Blocker",
    "BREACH": "Breach",
    "FIRST_STRIKE": "First Strike",
    "HIGH_MOBILITY": "High-Maneuver",
    "REPAIR": "Repair",
    "SUPPORT": "Support",
}


@dataclass(frozen=True)
class SchemaRulesInfo:
    keywords: tuple[str, ...] = ()
    can_attack_player: bool = True
    trigger_timings: frozenset[str] = frozenset()
    play_windows: frozenset[str] = frozenset()
    has_activated_main: bool = False
    has_activated_action: bool = False
    continuous_modifiers: tuple[dict, ...] = ()


@dataclass
class CardEffectSchemaIndex:
    cards: dict[str, dict] = field(default_factory=dict)
    clauses: dict[tuple[str, str], list[dict]] = field(default_factory=dict)
    continuous_effects: dict[str, list[dict]] = field(default_factory=dict)
    rules_info: dict[str, SchemaRulesInfo] = field(default_factory=dict)

    @staticmethod
    def normalize_id(card_id):
        if not isinstance(card_id, str):
            return None
        if "/" in card_id:
            return card_id.split("/")[-1].strip() or None
        return card_id.strip() or None

    def effect_clauses(self, card_id, timing):
        normalized = self.normalize_id(card_id)
        if normalized is None:
            return []
        return [deepcopy(clause) for clause in self.clauses.get((normalized, timing), [])]

    def continuous_for_card(self, card_id):
        normalized = self.normalize_id(card_id)
        if normalized is None:
            return []
        return [deepcopy(clause) for clause in self.continuous_effects.get(normalized, [])]

    def info(self, card_id):
        normalized = self.normalize_id(card_id)
        return self.rules_info.get(normalized)


class CardEffectSchemaLoader:
    def __init__(self, schema_paths=None):
        self.schema_paths = [Path(path) for path in (schema_paths or config.card_effect_schema_paths())]

    def load(self):
        index = CardEffectSchemaIndex()
        for path in self.schema_paths:
            self._load_file(path, index)
        self._build_rules_info(index)
        return index

    def _load_file(self, path, index):
        if not path.exists():
            raise SchemaLoadError(f"schema file not found: {path}")
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cards = payload.get("cards")
        if not isinstance(cards, list):
            raise SchemaLoadError(f"{path}: cards must be a list")
        for card in cards:
            self._load_card(path, card, index)

    def _load_card(self, path, card, index):
        if not isinstance(card, dict):
            raise SchemaLoadError(f"{path}: card entry must be a mapping")
        card_id = CardEffectSchemaIndex.normalize_id(card.get("card_id"))
        if not card_id:
            raise SchemaLoadError(f"{path}: card entry missing card_id")
        index.cards[card_id] = deepcopy(card)
        effects = card.get("effects") or []
        if not isinstance(effects, list):
            raise SchemaLoadError(f"{path}: {card_id}.effects must be a list")
        for effect_index, effect in enumerate(effects):
            self._load_effect(path, card_id, effect_index, effect, index)
        self._load_keyword_effects(card_id, card, index)

    def _load_effect(self, path, card_id, effect_index, effect, index):
        if not isinstance(effect, dict):
            raise SchemaLoadError(f"{path}: {card_id}.effects[{effect_index}] must be a mapping")
        kind = effect.get("kind")
        if kind not in {"triggered", "activated", "continuous"}:
            raise SchemaLoadError(f"{path}: {card_id}.effects[{effect_index}] invalid kind: {kind!r}")
        clause = deepcopy(effect)
        clause["source_card_id"] = card_id
        if kind == "continuous":
            index.continuous_effects.setdefault(card_id, []).append(clause)
            return
        timings = effect.get("timing")
        if not isinstance(timings, list):
            timings = [timings]
        for timing in timings:
            runtime_timing = _RUNTIME_TIMING_BY_SCHEMA.get(timing)
            if runtime_timing is None:
                raise SchemaLoadError(f"{path}: {card_id} unsupported timing: {timing!r}")
            indexed_clause = deepcopy(clause)
            indexed_clause["schema_timing"] = timing
            indexed_clause["runtime_timing"] = runtime_timing
            index.clauses.setdefault((card_id, runtime_timing), []).append(indexed_clause)
            if kind == "activated" and timing == "MAIN":
                activate_clause = deepcopy(indexed_clause)
                activate_clause["runtime_timing"] = "ACTIVATE_MAIN"
                index.clauses.setdefault((card_id, "ACTIVATE_MAIN"), []).append(activate_clause)
            if kind == "activated" and timing == "ACTION":
                activate_clause = deepcopy(indexed_clause)
                activate_clause["runtime_timing"] = "ACTIVATE_ACTION"
                index.clauses.setdefault((card_id, "ACTIVATE_ACTION"), []).append(activate_clause)

    def _load_keyword_effects(self, card_id, card, index):
        for keyword in card.get("keywords") or []:
            if not isinstance(keyword, dict):
                continue
            if keyword.get("keyword") != "REPAIR":
                continue
            value = int(keyword.get("value") or 0)
            if value <= 0:
                continue
            index.clauses.setdefault((card_id, "END_OF_TURN"), []).append({
                "source_card_id": card_id,
                "kind": "triggered",
                "timing": "END_OF_TURN",
                "schema_timing": "END_OF_TURN",
                "runtime_timing": "END_OF_TURN",
                "optional": False,
                "cost": "none",
                "resolution": {
                    "type": "simple",
                    "actions": [{"action": "heal", "target": "source", "amount": value}],
                },
            })

    def _build_rules_info(self, index):
        for card_id, card in index.cards.items():
            keywords = []
            for keyword in card.get("keywords") or []:
                if not isinstance(keyword, dict):
                    continue
                normalized = _KEYWORD_BY_SCHEMA.get(keyword.get("keyword"))
                if normalized and normalized not in keywords:
                    keywords.append(normalized)
                if normalized == "Breach" and keyword.get("value") is not None:
                    valued = f"Breach:{int(keyword.get('value') or 0)}"
                    if valued not in keywords:
                        keywords.append(valued)
                if normalized == "Support" and keyword.get("value") is not None:
                    valued = f"Support:{int(keyword.get('value') or 0)}"
                    if valued not in keywords:
                        keywords.append(valued)
            trigger_timings = set()
            play_windows = set()
            has_activated_main = False
            has_activated_action = False
            can_attack_player = True
            if any(keyword == "Support" or keyword.startswith("Support:") for keyword in keywords):
                has_activated_main = True
            for continuous in index.continuous_effects.get(card_id, []):
                if continuous.get("condition") not in (None, "none"):
                    continue
                target = continuous.get("target") or {}
                if target.get("scope") != "source":
                    continue
                for modifier in continuous.get("modifiers") or []:
                    restriction = modifier.get("restrict_attack") if isinstance(modifier, dict) else None
                    if restriction and restriction.get("cannot_target_player"):
                        can_attack_player = False
            for (indexed_card_id, timing), clauses in index.clauses.items():
                if indexed_card_id != card_id:
                    continue
                for clause in clauses:
                    if clause.get("kind") == "activated":
                        if timing in {"MAIN", "ACTION"}:
                            play_windows.add(timing)
                        if timing == "ACTIVATE_MAIN":
                            has_activated_main = True
                        if timing == "ACTIVATE_ACTION":
                            has_activated_action = True
                    else:
                        trigger_timings.add(timing)
            index.rules_info[card_id] = SchemaRulesInfo(
                keywords=tuple(keywords),
                can_attack_player=can_attack_player,
                trigger_timings=frozenset(trigger_timings),
                play_windows=frozenset(play_windows),
                has_activated_main=has_activated_main,
                has_activated_action=has_activated_action,
                continuous_modifiers=tuple(index.continuous_effects.get(card_id, [])),
            )
