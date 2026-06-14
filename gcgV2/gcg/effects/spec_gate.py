"""Spec gate：驗證 LLM interpreter 輸出的 effect spec。

LLM 輸出進入 executor 前的唯一入口。任何不在 dictionary 詞彙內的
primitive / timing / filter 一律拒絕，分類為 interpretation problem，
不執行、不猜測。
"""

from __future__ import annotations


class SpecGateError(ValueError):
    """Effect spec 未通過 schema 驗證。"""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# 各 requirement 允許的鍵
_REQUIREMENT_KEYS = {
    "name", "controller", "card_type", "zone", "status", "count",
    "hp_lte", "hp_gte", "ap_lte", "ap_gte", "level_lte", "level_gte",
    "damage_gte", "other_than_source", "damaged_only", "link_required",
    "trait_any", "keyword_has",
}

# step 內允許的鍵
_STEP_KEYS = {
    "primitive", "target", "amount", "duration", "condition", "steps",
    "else_steps", "ability", "tokens", "notes",
}

# step target 允許的特殊參照（除 $requirement 之外）
_SPECIAL_TARGETS = {
    "source", "self_player", "opponent_player", "self_resource",
    "self_shield_top", "self_all_unit", "opponent_all_unit",
    "self_all_link_unit", "self_base", "opponent_base",
}

# 引擎支援的 condition 型別（dictionary condition_patterns 的執行子集）
SUPPORTED_CONDITIONS = {
    "pilot_trait_any",
    "source_is_paired",
    "is_your_turn",
    "friendly_units_gte",
    "enemy_units_gte",
    "target_destroyed",
}


class SpecGate:
    def __init__(self, dictionary):
        self.dictionary = dictionary

    def validate(self, spec):
        """驗證 spec；失敗丟 SpecGateError，成功回傳 spec 本身。"""
        errors = []
        if not isinstance(spec, dict):
            raise SpecGateError(["effect spec must be a dict"])

        status = spec.get("status")
        if status not in self.dictionary.statuses:
            errors.append(f"invalid status: {status!r}")

        timing = spec.get("timing")
        if timing not in self.dictionary.timings:
            errors.append(f"invalid timing: {timing!r}")

        requirements = spec.get("target_requirements") or []
        if not isinstance(requirements, list):
            errors.append("target_requirements must be a list")
            requirements = []
        names = set()
        for index, requirement in enumerate(requirements):
            errors.extend(self._validate_requirement(requirement, index, names))

        if status == "resolved":
            steps = spec.get("primitive_steps")
            if not isinstance(steps, list) or not steps:
                errors.append("resolved spec must include non-empty primitive_steps")
            else:
                for index, step in enumerate(steps):
                    errors.extend(self._validate_step(step, f"primitive_steps[{index}]", names))
        elif status == "unsupported":
            if not spec.get("unsupported_capabilities"):
                errors.append("unsupported spec must list unsupported_capabilities")

        cost = spec.get("cost")
        if cost is not None:
            if not isinstance(cost, dict):
                errors.append("cost must be a dict")
            else:
                if "resources" in cost and not isinstance(cost["resources"], int):
                    errors.append("cost.resources must be an int")
                if "rest_source" in cost and not isinstance(cost["rest_source"], bool):
                    errors.append("cost.rest_source must be a bool")

        if errors:
            raise SpecGateError(errors)
        return spec

    def _validate_requirement(self, requirement, index, names):
        errors = []
        prefix = f"target_requirements[{index}]"
        if not isinstance(requirement, dict):
            return [f"{prefix} must be a dict"]
        unknown = set(requirement) - _REQUIREMENT_KEYS
        if unknown:
            errors.append(f"{prefix} has unknown keys: {sorted(unknown)}")
        name = requirement.get("name")
        if not name or not isinstance(name, str):
            errors.append(f"{prefix} requires a string name")
        else:
            names.add(name)
        controller = requirement.get("controller")
        if controller not in self.dictionary.target_controllers:
            errors.append(f"{prefix} invalid controller: {controller!r}")
        card_type = requirement.get("card_type")
        if card_type not in self.dictionary.target_card_types:
            errors.append(f"{prefix} invalid card_type: {card_type!r}")
        status = requirement.get("status")
        if status is not None and status not in self.dictionary.target_statuses:
            errors.append(f"{prefix} invalid status: {status!r}")
        count = requirement.get("count", 1)
        if not isinstance(count, int) or count < 1:
            errors.append(f"{prefix} count must be a positive int")
        for comparison in ("hp_lte", "hp_gte", "ap_lte", "ap_gte", "level_lte", "level_gte", "damage_gte"):
            if comparison in requirement:
                if comparison not in self.dictionary.target_comparisons:
                    errors.append(f"{prefix} comparison not in dictionary: {comparison}")
                elif not isinstance(requirement[comparison], int):
                    errors.append(f"{prefix} {comparison} must be an int")
        return errors

    def _validate_step(self, step, prefix, names):
        errors = []
        if not isinstance(step, dict):
            return [f"{prefix} must be a dict"]
        unknown = set(step) - _STEP_KEYS
        if unknown:
            errors.append(f"{prefix} has unknown keys: {sorted(unknown)}")
        primitive = step.get("primitive")
        if primitive not in self.dictionary.primitives:
            errors.append(f"{prefix} primitive not in dictionary: {primitive!r}")
        target = step.get("target")
        if target is not None:
            errors.extend(self._validate_target_ref(target, prefix, names))
        amount = step.get("amount")
        if amount is not None and not isinstance(amount, int):
            errors.append(f"{prefix} amount must be an int")
        condition = step.get("condition")
        if condition is not None:
            if not isinstance(condition, dict):
                errors.append(f"{prefix} condition must be a dict")
            elif condition.get("type") not in SUPPORTED_CONDITIONS:
                errors.append(f"{prefix} unsupported condition type: {condition.get('type')!r}")
        for child_key in ("steps", "else_steps"):
            child_steps = step.get(child_key)
            if child_steps is None:
                continue
            if not isinstance(child_steps, list):
                errors.append(f"{prefix}.{child_key} must be a list")
                continue
            for index, child in enumerate(child_steps):
                errors.extend(self._validate_step(child, f"{prefix}.{child_key}[{index}]", names))
        return errors

    def _validate_target_ref(self, target, prefix, names):
        if not isinstance(target, str):
            return [f"{prefix} target must be a string"]
        if target.startswith("$"):
            if target[1:] not in names:
                return [f"{prefix} target references unknown requirement: {target}"]
            return []
        if target in _SPECIAL_TARGETS:
            return []
        return [f"{prefix} invalid target ref: {target!r}"]
