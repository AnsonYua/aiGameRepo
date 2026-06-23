"""Deterministic interpreter backed by structured card effect schemas."""

from __future__ import annotations

from copy import deepcopy

from .dictionary import EffectDictionary
from .interpreter import EffectInterpreter
from .schema_loader import CardEffectSchemaLoader
from .spec_gate import SpecGate, SpecGateError


_ACTION_TO_PRIMITIVE = {
    "damage": "damage",
    "heal": "heal",
    "rest": "rest",
    "set_active": "setActive",
    "modify_ap": "modifyAP",
    "modify_hp": "modifyHP",
    "draw": "draw",
    "add_to_hand": "addToHand",
    "add_shield_to_hand": "addToHand",
    "return_to_hand": "returnToHand",
    "deploy": "deploy",
    "execute_own_effect": "activate_ability",
    "grant_keyword": "grant_keyword",
    "restrict_attack": "restrict_attack",
    "allow_attack_active": "allow_attack_target",
    "scry_top_deck": "scry_top_deck",
    "select_from_top_deck": "select_from_top_deck",
    "add_extra_energy": "addExtraEnergy",
    "deploy_token": "deploy_token",
    "discard": "discard",
    "grant_damage_prevention": "grant_damage_prevention",
}

_TRAIT_TRANSLATIONS = {
    "地球聯邦": "Earth Federation",
    "WB隊": "White Base Team",
    "新人類": "Newtype",
    "學園": "Academy",
    "新吉翁": "Neo Zeon",
    "吉翁": "Zeon",
    "流星作戰": "Operation Meteor",
    "OZ": "OZ",
    "地球聯合": "Earth Alliance",
    "札夫特": "ZAFT",
}

_KEYWORD_TRANSLATIONS = {
    "BLOCKER": "Blocker",
    "BREACH": "Breach",
    "FIRST_STRIKE": "First Strike",
    "HIGH_MOBILITY": "High-Maneuver",
    "REPAIR": "Repair",
    "SUPPORT": "Support",
}

_RUNTIME_TIMING_BY_SCHEMA = {
    "ON_BATTLE_DESTROY": "BATTLE_DESTROY",
    "ON_SHIELD_BREAK": "ON_SHIELD_BREAK",
    "ON_ATTACK": "ATTACK_PHASE",
    "ON_BOARD": "PAIRING_COMPLETE",
    "BURST": "BURST_CONDITION",
}

_EVENT_GATED_TIMINGS = {"ATTACK_PHASE", "BATTLE_DESTROY", "ON_SHIELD_BREAK"}


class SchemaEffectInterpreter(EffectInterpreter):
    """Drop-in EffectInterpreter that performs schema lookup instead of LLM calls."""

    def __init__(self, dictionary=None, schema_index=None, schema_paths=None):
        self.dictionary = dictionary or EffectDictionary()
        self.schema_index = schema_index or CardEffectSchemaLoader(schema_paths).load()
        self.spec_gate = SpecGate(self.dictionary)
        self._cache = {}

    def interpret(self, card, timing, context=None):
        card_id = card["id"]
        cache_key = (card_id, timing)
        if cache_key in self._cache:
            return deepcopy(self._cache[cache_key])

        clauses = self.schema_index.effect_clauses(card_id, timing)
        if not clauses:
            spec = self._unsupported(card_id, timing, f"no schema clause for {card_id}@{timing}")
        else:
            spec = self._build_spec(card_id, timing, clauses)

        if spec.get("status") == "resolved":
            try:
                spec = self.spec_gate.validate(spec)
            except SpecGateError as exc:
                spec = self._unsupported(card_id, timing, f"schema bridge output failed SpecGate: {exc}")

        self._cache[cache_key] = deepcopy(spec)
        return deepcopy(spec)

    def build_granted_trigger_spec(self, source_card_id, granted_effect):
        timing = _RUNTIME_TIMING_BY_SCHEMA.get(granted_effect.get("timing"), granted_effect.get("timing"))
        clause = deepcopy(granted_effect)
        clause["source_card_id"] = source_card_id
        clause["runtime_timing"] = timing
        # Event guard conditions are checked by TriggerSystem before enqueue.
        clause["condition"] = None
        spec = self._build_spec(source_card_id, timing, [clause])
        if spec.get("status") == "resolved":
            return self.spec_gate.validate(spec)
        return spec

    def _build_spec(self, card_id, timing, clauses):
        requirements = []
        steps = []
        unsupported = []
        target_aliases = {}
        optional = False
        once_per_turn = False
        cost = {}

        for clause in clauses:
            clause_optional = bool(clause.get("optional"))
            # Existing runtime treats Burst as an optional trigger choice.
            if timing == "BURST_CONDITION":
                clause_optional = True
            optional = optional or clause_optional
            once_per_turn = once_per_turn or clause.get("frequency") == "once_per_turn"
            cost.update(self._convert_cost(clause.get("cost"), unsupported))

            converted_requirements, target_ref, aliases = self._convert_target(
                clause.get("target"),
                requirements,
                default_status=self._default_target_status(clause),
            )
            requirements.extend(converted_requirements)
            target_aliases.update(aliases)
            clause_steps = self._convert_resolution(
                clause.get("resolution"), target_ref, target_aliases, unsupported
            )
            condition = clause.get("condition")
            if condition not in (None, "none"):
                converted_condition = self._convert_condition(
                    condition,
                    unsupported,
                    allow_event_guards=timing in _EVENT_GATED_TIMINGS,
                )
                if converted_condition is not None:
                    clause_steps = [{
                        "primitive": "conditional",
                        "condition": converted_condition,
                        "steps": clause_steps,
                    }]
            steps.extend(clause_steps)

        if unsupported:
            return self._unsupported(card_id, timing, "; ".join(unsupported))

        spec = {
            "status": "resolved",
            "source_card_id": card_id,
            "timing": timing,
            "optional": optional,
            "once_per_turn": once_per_turn,
            "target_requirements": requirements,
            "primitive_steps": steps,
            "unsupported_capabilities": [],
            "notes": "schema interpretation",
        }
        if cost:
            spec["cost"] = {
                "resources": int(cost.get("resources") or 0),
                "rest_source": bool(cost.get("rest_source")),
            }
        return spec

    def _convert_cost(self, schema_cost, unsupported):
        if schema_cost in (None, "none"):
            return {}
        if not isinstance(schema_cost, list):
            unsupported.append(f"unsupported cost shape: {schema_cost!r}")
            return {}
        cost = {}
        for item in schema_cost:
            cost_type = item.get("type")
            if cost_type == "pay_resource":
                cost["resources"] = int(item.get("amount") or 0)
            elif cost_type == "rest" and item.get("target") == "source":
                cost["rest_source"] = True
            else:
                unsupported.append(f"unsupported cost type: {cost_type}")
        return cost

    def _convert_target(self, target, existing_requirements, default_status=None):
        if target in (None, "none"):
            return [], None, {}
        if not isinstance(target, dict):
            return [], None, {}
        scope = target.get("scope")
        name = target.get("name") or f"t{len(existing_requirements) + 1}"
        if scope:
            target_ref = self._scope_to_target(scope, target)
            aliases = {name: target_ref} if target.get("name") else {}
            return [], target_ref, aliases
        requirement = {
            "name": name,
            "controller": target.get("controller", "any"),
            "card_type": self._normalize_card_type(target.get("card_type")),
            "count": int(target.get("count") or 1),
        }
        status = target.get("status") or default_status
        if status:
            requirement["status"] = status
        self._add_comparisons(requirement, target.get("comparisons") or [])
        extra_filters = target.get("extra_filters") or {}
        if extra_filters.get("trait_any"):
            requirement["trait_any"] = [self._translate_trait(value) for value in extra_filters["trait_any"]]
        if extra_filters.get("keyword_has"):
            requirement["keyword_has"] = self._translate_keyword(extra_filters["keyword_has"])
        if extra_filters.get("resonance_active"):
            requirement["link_required"] = True
        if extra_filters.get("other_than_source"):
            requirement["other_than_source"] = True
        return [requirement], f"${name}", {}

    def _scope_to_target(self, scope, target):
        if scope == "source":
            return "source"
        suffix = self._scope_filter_suffix(target)
        if scope == "self_all_unit":
            if (target.get("extra_filters") or {}).get("resonance_active"):
                return "self_all_link_unit"
            return f"self_all_unit{suffix}"
        if scope == "opponent_all_unit":
            return f"opponent_all_unit{suffix}"
        if scope == "self_all_link_unit":
            return "self_all_link_unit"
        if scope == "paired_unit":
            return "source"
        return scope

    def _scope_filter_suffix(self, target):
        comparisons = target.get("comparisons") or []
        if not comparisons:
            return ""
        parts = []
        for comparison in comparisons:
            field = comparison.get("field")
            op = comparison.get("op")
            value = comparison.get("value")
            if field in {"level", "ap", "hp"} and op in {"lte", "gte"} and isinstance(value, int):
                parts.append(f"{field}_{op}_{value}")
        return "_" + "_".join(parts) if parts else ""

    def _convert_resolution(self, resolution, default_target, target_aliases, unsupported):
        if not isinstance(resolution, dict):
            unsupported.append("missing resolution")
            return []
        resolution_type = resolution.get("type")
        if resolution_type == "simple":
            return self._convert_actions(
                resolution.get("actions") or [], default_target, target_aliases, unsupported
            )
        if resolution_type == "sequence":
            return [{
                "primitive": "sequence",
                "steps": self._convert_sequence_steps(
                    resolution.get("steps") or [], target_aliases, unsupported
                ),
            }]
        if resolution_type == "conditional_chain":
            token_step = self._try_conditional_token_deploy(resolution)
            if token_step is not None:
                return [token_step]
            chain_step = self._convert_conditional_chain(resolution, default_target, target_aliases, unsupported)
            return [chain_step] if chain_step is not None else []
        if resolution_type == "conditional":
            condition = self._convert_condition(resolution.get("condition"), unsupported)
            then_steps = self._convert_actions(
                resolution.get("actions") or [], default_target, target_aliases, unsupported
            )
            return [{"primitive": "conditional", "condition": condition or {}, "steps": then_steps}]
        unsupported.append(f"unsupported resolution type: {resolution_type}")
        return []

    def _convert_sequence_steps(self, steps, target_aliases, unsupported):
        converted = []
        for step in steps:
            child_steps = []
            if step.get("actions"):
                child_steps.extend(
                    self._convert_actions(step.get("actions") or [], None, target_aliases, unsupported)
                )
            if step.get("resolution"):
                child_steps.extend(
                    self._convert_resolution(step.get("resolution"), None, target_aliases, unsupported)
                )
            condition = step.get("condition")
            if condition not in (None, "none"):
                converted_condition = self._convert_condition(condition, unsupported)
                child_steps = [{
                    "primitive": "conditional",
                    "condition": converted_condition or {},
                    "steps": child_steps,
                }]
            converted.extend(child_steps)
        return converted

    def _convert_actions(self, actions, default_target, target_aliases, unsupported):
        converted = []
        for action in actions:
            action_name = action.get("action")
            primitive = _ACTION_TO_PRIMITIVE.get(action_name)
            if primitive is None:
                unsupported.append(f"unsupported action: {action_name}")
                continue
            step = {"primitive": primitive}
            if primitive == "addToHand" and action_name == "add_shield_to_hand":
                step["target"] = "self_shield_top"
            elif primitive == "activate_ability":
                step["ability"] = "main"
            else:
                target = self._convert_action_target(action.get("target"), default_target, target_aliases)
                if target is not None:
                    step["target"] = target
            for key in ("amount", "duration", "value"):
                if key in action:
                    step[key if key != "value" else "amount"] = action[key]
            for key in ("cannot_attack", "cannot_target_player", "attack_target_filter"):
                if key in action:
                    step[key] = action[key]
            if "token" in action:
                step["token"] = self._convert_token_spec(action["token"])
            if "choices" in action:
                # Deterministic runtime default: choose the first listed token option.
                step["token"] = self._convert_token_spec((action.get("choices") or [{}])[0])
            for key in ("filter", "count", "to", "remainder", "reveal", "source_filter", "damage_type"):
                if key in action:
                    value = deepcopy(action[key])
                    if key in {"filter", "source_filter"} and isinstance(value, dict):
                        if value.get("trait_any"):
                            value["trait_any"] = [self._translate_trait(item) for item in value["trait_any"]]
                    step[key] = value
            if "keyword" in action:
                step["keyword"] = self._translate_keyword(action["keyword"])
            converted.append(step)
        return converted

    def _convert_action_target(self, target, default_target, target_aliases):
        if target in (None, "chosen"):
            return default_target
        if target == "this_unit":
            return "source"
        if isinstance(target, str) and target.startswith("$"):
            alias = target_aliases.get(target[1:])
            if alias is not None:
                return alias
            return target
        return target

    def _default_target_status(self, clause):
        target = clause.get("target") or {}
        if target.get("status") or self._normalize_card_type(target.get("card_type")) != "unit":
            return None
        resolution = clause.get("resolution") or {}
        actions = resolution.get("actions") or []
        if len(actions) == 1 and actions[0].get("action") == "rest":
            return "active"
        return None

    def _convert_condition(self, condition, unsupported, allow_event_guards=False):
        if not isinstance(condition, dict):
            unsupported.append(f"unsupported condition shape: {condition!r}")
            return None
        if "all_of" in condition:
            converted = []
            for child in condition.get("all_of") or []:
                child_condition = self._convert_condition(
                    child,
                    unsupported,
                    allow_event_guards=allow_event_guards,
                )
                if child_condition is not None:
                    converted.append(child_condition)
            if not converted:
                return None
            if len(converted) == 1:
                return converted[0]
            return {"type": "all_of", "conditions": converted}
        condition_type = condition.get("type")
        if condition_type == "pilot_trait_any":
            return {
                "type": "pilot_trait_any",
                "traits": [self._translate_trait(value) for value in condition.get("traits") or []],
            }
        if condition_type == "source_is_paired":
            return {"type": "source_is_paired"}
        if condition_type == "turn_side_is" and condition.get("side") == "self":
            return {"type": "is_your_turn"}
        if condition_type in {"event_source_is", "destroyed_unit_controller_is"}:
            if not allow_event_guards:
                unsupported.append(f"event-only condition cannot be evaluated in effect spec: {condition_type}")
            return None
        if condition_type in {"pilot_level", "source_ap"}:
            return {
                "type": condition_type,
                "op": condition.get("op"),
                "value": int(condition.get("value") or 0),
            }
        if condition_type in {"resonance_active", "another_link_unit_exists", "trash_card_name_contains", "board_count"}:
            converted = deepcopy(condition)
            converted["type"] = condition_type
            extra = converted.get("extra_filters") or {}
            if extra.get("trait_any"):
                extra["trait_any"] = [self._translate_trait(value) for value in extra["trait_any"]]
                converted["extra_filters"] = extra
            return converted
        if "not" in condition:
            child = self._convert_condition(
                condition.get("not"),
                unsupported,
                allow_event_guards=allow_event_guards,
            )
            return {"type": "not", "condition": child} if child is not None else None
        unsupported.append(f"unsupported condition type: {condition_type}")
        return None

    def _convert_token_spec(self, token):
        token = dict(token or {})
        if token.get("name"):
            token["name"] = self._translate_token_name(token["name"])
        if "base_ap" in token and "ap" not in token:
            token["ap"] = token["base_ap"]
        if "base_hp" in token and "hp" not in token:
            token["hp"] = token["base_hp"]
        keywords = []
        for keyword in token.get("keywords") or []:
            if isinstance(keyword, dict):
                translated = self._translate_keyword(keyword.get("keyword"))
                if translated:
                    keywords.append(translated)
        if keywords:
            token["keywords"] = keywords
        return token

    def _try_conditional_token_deploy(self, resolution):
        tokens = []
        for branch in resolution.get("branches") or []:
            condition = branch.get("condition") or {}
            if condition.get("type") != "board_count":
                return None
            actions = branch.get("actions") or []
            if len(actions) != 1 or actions[0].get("action") != "deploy_token":
                return None
            token = actions[0].get("token") or {}
            token_spec = {
                "name": self._translate_token_name(token.get("name")),
                "ap": int(token.get("ap") if token.get("ap") is not None else token.get("base_ap") or 0),
                "hp": int(token.get("hp") if token.get("hp") is not None else token.get("base_hp") or 0),
            }
            op = condition.get("op")
            value = int(condition.get("value") or 0)
            if op == "eq":
                token_spec["unit_count"] = value
            elif op == "gte":
                token_spec["unit_count_gte"] = value
            elif op == "lte":
                token_spec["unit_count_lte"] = value
            else:
                return None
            tokens.append(token_spec)
        return {"primitive": "conditionalTokenDeploy", "tokens": tokens}

    def _convert_conditional_chain(self, resolution, default_target, target_aliases, unsupported):
        next_step = None
        for branch in reversed(resolution.get("branches") or []):
            condition = self._convert_condition(branch.get("condition"), unsupported)
            if condition is None:
                return None
            steps = self._convert_actions(
                branch.get("actions") or [], default_target, target_aliases, unsupported
            )
            current = {"primitive": "conditional", "condition": condition, "steps": steps}
            if next_step is not None:
                current["else_steps"] = [next_step]
            next_step = current
        if next_step is None:
            unsupported.append("conditional_chain has no branches")
        return next_step

    def _add_comparisons(self, requirement, comparisons):
        for comparison in comparisons:
            field = comparison.get("field")
            op = comparison.get("op")
            value = comparison.get("value")
            if field in {"hp", "ap", "level", "damage"} and op in {"lte", "gte"}:
                requirement[f"{field}_{op}"] = int(value)

    def _normalize_card_type(self, card_type):
        if card_type is None:
            return "unit"
        return str(card_type).lower()

    def _translate_trait(self, value):
        return _TRAIT_TRANSLATIONS.get(value, value)

    def _translate_keyword(self, value):
        return _KEYWORD_TRANSLATIONS.get(value, value)

    def _translate_token_name(self, value):
        return {
            "高達": "Gundam",
            "鋼加農": "Guncannon",
            "鋼坦克": "GunTank",
        }.get(value, value)

    def _unsupported(self, card_id, timing, reason):
        return {
            "status": "unsupported",
            "source_card_id": card_id,
            "timing": timing,
            "target_requirements": [],
            "primitive_steps": [],
            "unsupported_capabilities": [reason],
            "notes": "schema interpretation",
        }
