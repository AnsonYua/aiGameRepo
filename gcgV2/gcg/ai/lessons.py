"""Lesson / experience summary retrieval（非策略引擎，只做檢索與格式化）。

條件匹配只依 lesson 自行宣告的 `condition:` 與 public viewer state 數量特徵
做檢索過濾；送進 prompt 的只有 description 文字，是否採用由 LLM 決定。
`effect:` / `score_bonus` 是舊評分引擎遺留欄位，這裡不讀取、不評分。
"""

from __future__ import annotations

import yaml

from .. import config

_DEFAULT_MAX_LESSONS = 4


def load_experience_summaries(experience_root=None):
    root = experience_root or config.experience_root()
    summaries = {}
    if not root.exists():
        return summaries
    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        lesson_id = data.get("id") or path.stem
        summaries[lesson_id] = {
            "id": lesson_id,
            "summary": data.get("description") or data.get("summary") or "",
            "source": str(path),
            "priority": data.get("priority", 0),
            "condition": data.get("condition") or {},
        }
    return summaries


def select_summaries(summaries, lesson_ids):
    return [
        _public_entry(summaries[lesson_id])
        for lesson_id in lesson_ids
        if lesson_id in summaries
    ]


def match_summaries(summaries, features, max_lessons=_DEFAULT_MAX_LESSONS):
    """依 lesson 宣告的 condition 過濾，回傳 priority 最高的前幾條。"""
    matched = [
        entry for entry in summaries.values()
        if _condition_matches(entry.get("condition") or {}, features)
    ]
    matched.sort(key=lambda entry: entry.get("priority", 0), reverse=True)
    return [_public_entry(entry) for entry in matched[:max_lessons]]


def _public_entry(entry):
    return {"id": entry["id"], "summary": entry["summary"], "source": entry["source"]}


_CONDITION_CHECKS = {
    "turn_min": lambda features, value: features.get("turn", 0) >= value,
    "turn_max": lambda features, value: features.get("turn", 0) <= value,
    "my_units_min": lambda features, value: features.get("my_units", 0) >= value,
    "my_units_max": lambda features, value: features.get("my_units", 0) <= value,
    "my_empty_slots_min": lambda features, value: features.get("my_empty_slots", 0) >= value,
    "my_empty_slots_max": lambda features, value: features.get("my_empty_slots", 0) <= value,
    "enemy_units_min": lambda features, value: features.get("enemy_units", 0) >= value,
    "enemy_units_max": lambda features, value: features.get("enemy_units", 0) <= value,
    "enemy_rested_units_min": lambda features, value: features.get("enemy_rested_units", 0) >= value,
    "enemy_damaged_units_min": lambda features, value: features.get("enemy_damaged_units", 0) >= value,
    "my_base_hp_max": lambda features, value: features.get("my_base_hp", 0) <= value,
    "my_base_present": lambda features, value: features.get("my_base_present", False) == bool(value),
    "my_shields_min": lambda features, value: features.get("my_shields", 0) >= value,
    "my_shields_max": lambda features, value: features.get("my_shields", 0) <= value,
    "enemy_base_present": lambda features, value: features.get("enemy_base_present", False) == bool(value),
    "enemy_shields_min": lambda features, value: features.get("enemy_shields", 0) >= value,
    "enemy_shields_max": lambda features, value: features.get("enemy_shields", 0) <= value,
    "has_link_units": lambda features, value: features.get("has_link_units", False) == bool(value),
    "my_active_units_min": lambda features, value: features.get("my_active_units", 0) >= value,
    "has_unpaired_units": lambda features, value: features.get("has_unpaired_units", False) == bool(value),
    "has_temp_debuff_in_hand": lambda features, value: (
        features.get("has_temp_debuff_in_hand", False) == bool(value)
    ),
    "has_matching_pilot_in_hand": lambda features, value: (
        features.get("has_matching_pilot_in_hand", False) == bool(value)
    ),
    "enemy_active_units_min": lambda features, value: features.get("enemy_active_units", 0) >= value,
    "enemy_active_units_max": lambda features, value: features.get("enemy_active_units", 0) <= value,
    "has_pilot_in_hand": lambda features, value: (
        features.get("has_pilot_in_hand", False) == bool(value)
    ),
    "has_attack_restricted_unit": lambda features, value: (
        features.get("has_attack_restricted_unit", False) == bool(value)
    ),
    "has_pairable_in_hand": lambda features, value: (
        features.get("has_pairable_in_hand", False) == bool(value)
    ),
    "has_base_in_hand": lambda features, value: (
        features.get("has_base_in_hand", False) == bool(value)
    ),
    "enemy_base_hp_max": lambda features, value: features.get("enemy_base_hp", 0) <= value,
    "my_blocker_count_min": lambda features, value: features.get("my_blocker_count", 0) >= value,
    "my_blocker_count_max": lambda features, value: features.get("my_blocker_count", 0) <= value,
}


def _condition_matches(condition, features):
    for key, value in condition.items():
        check = _CONDITION_CHECKS.get(key)
        if check is None:
            return False
        if not check(features, value):
            return False
    return True
