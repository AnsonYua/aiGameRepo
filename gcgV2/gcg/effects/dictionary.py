"""Effect dictionary harness loading.

GCG_V2_EFFECT_DICTIONARY.yaml 是 LLM interpreter 的封閉詞彙表：
- primitives：runtime 能執行的原子操作
- timings：觸發時機
- target_filters / condition_patterns：可用的過濾與條件詞彙

LLM 只能用這份詞彙組合 effect spec；spec gate 會逐項驗證。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .. import config

# 主動使用時機（非觸發），dictionary timings 之外額外允許
PLAY_TIMINGS = {"MAIN", "ACTION", "ACTIVATE_MAIN"}


class EffectDictionary:
    def __init__(self, manifest_path=None):
        path = Path(manifest_path or config.effect_dictionary_path())
        self.path = path
        self.data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.keywords = set(self.data.get("keywords") or [])
        self.timings = set(self.data.get("timings") or []) | set(PLAY_TIMINGS)
        self.primitives = self._flatten(self.data.get("primitives") or {})
        self.statuses = set(
            (self.data.get("output_schema") or {}).get("status", {}).get("allowed")
            or ["resolved", "unresolved", "unsupported"]
        )
        target_filters = self.data.get("target_filters") or {}
        self.target_controllers = set(target_filters.get("controller") or [])
        self.target_card_types = set(target_filters.get("card_type") or [])
        self.target_statuses = set(target_filters.get("status") or [])
        self.target_comparisons = set(target_filters.get("comparisons") or [])
        self.target_scopes = set(target_filters.get("scope") or [])
        self.condition_patterns = self._flatten(self.data.get("condition_patterns") or {})

    def manifest_text(self):
        return self.path.read_text(encoding="utf-8")

    def _flatten(self, groups):
        flattened = set()
        for values in groups.values():
            if isinstance(values, list):
                flattened.update(values)
        return flattened
