"""Deterministic per-card detection index.

這層只做「偵測」，不做語意解讀：

- 這張卡有沒有某個 timing 的觸發效果（[Deploy] / [Burst] / <Repair> ...）
- 是不是 Blocker、能不能攻擊玩家
- 是不是 pilot designation command、有沒有 [Activate/Main] 能力
- 連續性修正（例如 [During Pair] 全體 AP+1）的結構化參數

效果「做什麼」一律交給 effect interpreter（LLM）輸出 primitive_steps。
偵測來源優先用卡牌 JSON 的結構化 ``effects.rules``，缺漏時退回文字標籤。
"""

from __future__ import annotations

import re


_TEXT_TAG_TIMINGS = (
    (re.compile(r"\[Deploy\]", re.IGNORECASE), "ENTERS_PLAY"),
    (re.compile(r"\[Burst\]", re.IGNORECASE), "BURST_CONDITION"),
    (re.compile(r"\[When Paired", re.IGNORECASE), "PAIRING_COMPLETE"),
    (re.compile(r"\[Attack\]", re.IGNORECASE), "ATTACK_PHASE"),
    (re.compile(r"\[Destroyed\]", re.IGNORECASE), "DESTROYED"),
    (re.compile(r"<Repair\s+\d+>", re.IGNORECASE), "END_OF_TURN"),
)


class RulesIndex:
    def __init__(self, card_database):
        self.card_database = card_database
        self._cache = {}

    def info(self, card_id):
        normalized = self.card_database.normalize_id(card_id)
        if normalized in self._cache:
            return self._cache[normalized]
        card = self.card_database.get(card_id)
        info = self._build_info(card) if card is not None else self._empty_info()
        self._cache[normalized] = info
        return info

    # ------------------------------------------------------------------
    # query helpers
    # ------------------------------------------------------------------

    def keywords(self, card_id):
        return list(self.info(card_id)["keywords"])

    def is_blocker(self, card_id):
        return "Blocker" in self.info(card_id)["keywords"]

    def can_attack_player(self, card_id):
        return self.info(card_id)["can_attack_player"]

    def trigger_timings(self, card_id):
        return set(self.info(card_id)["trigger_timings"])

    def has_trigger(self, card_id, timing):
        return timing in self.info(card_id)["trigger_timings"]

    def play_windows(self, card_id):
        """Command 卡可使用的時機：MAIN / ACTION 子集合。"""
        return set(self.info(card_id)["play_windows"])

    def pilot_designation(self, card_id):
        """[Pilot][Name] 指定：回傳 {name, ap, hp} 或 None。"""
        return self.info(card_id)["pilot_designation"]

    def has_activated_main(self, card_id):
        return self.info(card_id)["has_activated_main"]

    def continuous_modifiers(self, card_id):
        return list(self.info(card_id)["continuous_modifiers"])

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------

    def _build_info(self, card):
        rules = list(card.get("effects", {}).get("rules", []))
        text = " ".join(card.get("effects", {}).get("description", []))

        keywords = []
        can_attack_player = True
        trigger_timings = set()
        play_windows = set()
        pilot_designation = None
        has_activated_main = False
        continuous_modifiers = []

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            action = rule.get("action")
            rule_type = rule.get("type")
            timing = rule.get("timing") or {}
            event_trigger = timing.get("eventTrigger")
            windows = set(timing.get("activationWindows") or [])

            if action == "redirect_attack" or rule.get("effectId") == "blocker":
                if "Blocker" not in keywords:
                    keywords.append("Blocker")
                continue
            if action == "restrict_attack":
                disallow = (rule.get("parameters") or {}).get("disallow")
                if disallow == "player":
                    can_attack_player = False
                continue
            if action == "designate_pilot":
                params = rule.get("parameters") or {}
                pilot_designation = {
                    "name": params.get("pilotName"),
                    "ap": int(params.get("AP") or 0),
                    "hp": int(params.get("HP") or 0),
                }
                continue
            if rule_type == "activated":
                if not windows or "MAIN_PHASE" in windows:
                    has_activated_main = True
                continue
            if rule_type == "continuous" or (timing.get("duration") == "continuous"):
                continuous_modifiers.append(self._build_continuous_modifier(rule))
                continue
            if rule_type == "play":
                if "MAIN_PHASE" in windows:
                    play_windows.add("MAIN")
                if "ACTION_STEP" in windows:
                    play_windows.add("ACTION")
                continue
            if event_trigger:
                trigger_timings.add(event_trigger)

        # 文字標籤 fallback / 補強
        for pattern, timing_name in _TEXT_TAG_TIMINGS:
            if pattern.search(text):
                trigger_timings.add(timing_name)
        if "<Blocker>" in text and "Blocker" not in keywords:
            keywords.append("Blocker")
        if "can't choose the enemy player as its attack target" in text.lower():
            can_attack_player = False
        if re.search(r"\[Main\]", text):
            play_windows.add("MAIN")
        if re.search(r"\[Main\]/\[Action\]|\[Action\]Choose", text):
            play_windows.add("ACTION")
        if re.search(r"\[Activate/Main\]", text):
            has_activated_main = True

        return {
            "keywords": keywords,
            "can_attack_player": can_attack_player,
            "trigger_timings": trigger_timings,
            "play_windows": play_windows,
            "pilot_designation": pilot_designation,
            "has_activated_main": has_activated_main,
            "continuous_modifiers": [mod for mod in continuous_modifiers if mod is not None],
        }

    def _build_continuous_modifier(self, rule):
        """目前支援的連續效果 pattern：配對中、全體我方 Unit、AP 修正。"""
        if rule.get("action") != "modifyAP":
            return None
        params = rule.get("parameters") or {}
        timing = rule.get("timing") or {}
        source_conditions = rule.get("sourceConditions") or []
        requires_paired = any(
            isinstance(cond, dict) and cond.get("type") == "paired"
            for cond in source_conditions
        )
        return {
            "action": "modifyAP",
            "value": int(params.get("value") or 0),
            "requires_paired": requires_paired,
            "your_turn_only": timing.get("actionTurn") == "YOUR_TURN",
            "scope": "self_all_unit",
        }

    def _empty_info(self):
        return {
            "keywords": [],
            "can_attack_player": True,
            "trigger_timings": set(),
            "play_windows": set(),
            "pilot_designation": None,
            "has_activated_main": False,
            "continuous_modifiers": [],
        }
