"""Reference interpreter for the ST01 set（測試 / 離線 harness 專用）。

這是 ST01 各卡效果的「人工標準答案」spec 集合：

- 用途 1：engine 回歸測試（不需要 LLM 也能驗證 trigger / resolve loop / executor）
- 用途 2：離線跑模擬 demo
- 用途 3：對照 LLM interpreter 的輸出品質

正式路徑仍是 LlmEffectInterpreter 即時解讀；這個檔案不是策略引擎，
也不應該被擴張成「每張卡 hardcode」的主路徑。
所有 spec 在建構時都會過 SpecGate 自我驗證。
"""

from __future__ import annotations

from copy import deepcopy

from .dictionary import EffectDictionary
from .interpreter import EffectInterpreter
from .spec_gate import SpecGate


def _spec(source_card_id, timing, **kwargs):
    spec = {
        "status": "resolved",
        "source_card_id": source_card_id,
        "timing": timing,
        "optional": False,
        "once_per_turn": False,
        "target_requirements": [],
        "primitive_steps": [],
        "unsupported_capabilities": [],
        "notes": "reference interpretation",
    }
    spec.update(kwargs)
    return spec


_SPECS = {
    # <Repair 2>：回合結束時恢復 2 HP
    ("ST01-001", "END_OF_TURN"): _spec(
        "ST01-001", "END_OF_TURN",
        primitive_steps=[{"primitive": "heal", "target": "source", "amount": 2}],
    ),
    # [When Paired (White Base Team) pilot]Draw 1
    ("ST01-002", "PAIRING_COMPLETE"): _spec(
        "ST01-002", "PAIRING_COMPLETE",
        primitive_steps=[{
            "primitive": "conditional",
            "condition": {"type": "pilot_trait_any", "traits": ["White Base Team"]},
            "steps": [{"primitive": "draw", "amount": 1}],
        }],
    ),
    # [Deploy]Choose 1 enemy Unit with 2 or less HP. Rest it.
    ("ST01-004", "ENTERS_PLAY"): _spec(
        "ST01-004", "ENTERS_PLAY",
        target_requirements=[{
            "name": "t1", "controller": "opponent", "card_type": "unit",
            "status": "active", "hp_lte": 2, "count": 1,
        }],
        primitive_steps=[{"primitive": "rest", "target": "$t1"}],
    ),
    # [When Paired]Choose 1 enemy Unit that is Lv.5 or lower. It gets AP-3 during this turn.
    ("ST01-006", "PAIRING_COMPLETE"): _spec(
        "ST01-006", "PAIRING_COMPLETE",
        target_requirements=[{
            "name": "t1", "controller": "opponent", "card_type": "unit",
            "level_lte": 5, "count": 1,
        }],
        primitive_steps=[{
            "primitive": "modifyAP", "target": "$t1", "amount": -3, "duration": "this_turn",
        }],
    ),
    # ST01-010 Amuro：[Burst]Add this card to your hand.
    ("ST01-010", "BURST_CONDITION"): _spec(
        "ST01-010", "BURST_CONDITION",
        optional=True,
        primitive_steps=[{"primitive": "addToHand", "target": "source"}],
    ),
    # ST01-010：[When Paired]Choose 1 enemy Unit with 5 or less HP. Rest it.
    ("ST01-010", "PAIRING_COMPLETE"): _spec(
        "ST01-010", "PAIRING_COMPLETE",
        target_requirements=[{
            "name": "t1", "controller": "opponent", "card_type": "unit",
            "status": "active", "hp_lte": 5, "count": 1,
        }],
        primitive_steps=[{"primitive": "rest", "target": "$t1"}],
    ),
    # ST01-011 Suletta：[Burst]Add this card to your hand.
    ("ST01-011", "BURST_CONDITION"): _spec(
        "ST01-011", "BURST_CONDITION",
        optional=True,
        primitive_steps=[{"primitive": "addToHand", "target": "source"}],
    ),
    # ST01-011：[Attack][Once per Turn]Choose 1 of your Resources. Set it as active.
    ("ST01-011", "ATTACK_PHASE"): _spec(
        "ST01-011", "ATTACK_PHASE",
        once_per_turn=True,
        target_requirements=[{
            "name": "t1", "controller": "self", "card_type": "resource", "count": 1,
        }],
        primitive_steps=[{"primitive": "setActive", "target": "self_resource"}],
    ),
    # ST01-012：[Main]Choose 1 rested enemy Unit. Deal 1 damage to it.
    ("ST01-012", "MAIN"): _spec(
        "ST01-012", "MAIN",
        target_requirements=[{
            "name": "t1", "controller": "opponent", "card_type": "unit",
            "status": "rested", "count": 1,
        }],
        primitive_steps=[{"primitive": "damage", "target": "$t1", "amount": 1}],
    ),
    # ST01-013：[Main]Choose 1 friendly Unit. It recovers 3 HP.
    ("ST01-013", "MAIN"): _spec(
        "ST01-013", "MAIN",
        target_requirements=[{
            "name": "t1", "controller": "self", "card_type": "unit", "count": 1,
        }],
        primitive_steps=[{"primitive": "heal", "target": "$t1", "amount": 3}],
    ),
    # ST01-014：[Main]/[Action]Choose 1 enemy Unit. It gets AP-3 during this turn.
    ("ST01-014", "MAIN"): _spec(
        "ST01-014", "MAIN",
        target_requirements=[{
            "name": "t1", "controller": "opponent", "card_type": "unit", "count": 1,
        }],
        primitive_steps=[{
            "primitive": "modifyAP", "target": "$t1", "amount": -3, "duration": "this_turn",
        }],
    ),
    # ST01-014：[Burst]Activate this card's [Main].
    ("ST01-014", "BURST_CONDITION"): _spec(
        "ST01-014", "BURST_CONDITION",
        optional=True,
        primitive_steps=[{"primitive": "activate_ability", "ability": "main"}],
    ),
    # ST01-015 White Base：[Burst]Deploy this card.
    ("ST01-015", "BURST_CONDITION"): _spec(
        "ST01-015", "BURST_CONDITION",
        optional=True,
        primitive_steps=[{"primitive": "deploy", "target": "source"}],
    ),
    # ST01-015：[Deploy]Add 1 of your Shields to your hand.
    ("ST01-015", "ENTERS_PLAY"): _spec(
        "ST01-015", "ENTERS_PLAY",
        primitive_steps=[{"primitive": "addToHand", "target": "self_shield_top"}],
    ),
    # ST01-015：[Activate/Main][Once per Turn](2): 條件式 token 部署
    ("ST01-015", "ACTIVATE_MAIN"): _spec(
        "ST01-015", "ACTIVATE_MAIN",
        once_per_turn=True,
        cost={"resources": 2, "rest_source": False},
        primitive_steps=[{
            "primitive": "conditionalTokenDeploy",
            "tokens": [
                {"unit_count": 0, "name": "Gundam", "ap": 3, "hp": 3},
                {"unit_count": 1, "name": "Guncannon", "ap": 2, "hp": 2},
                {"unit_count_gte": 2, "name": "GunTank", "ap": 1, "hp": 1},
            ],
        }],
    ),
    # ST01-016：[Burst]Deploy this card.
    ("ST01-016", "BURST_CONDITION"): _spec(
        "ST01-016", "BURST_CONDITION",
        optional=True,
        primitive_steps=[{"primitive": "deploy", "target": "source"}],
    ),
    # ST01-016：[Deploy]Add 1 of your Shields to your hand.
    ("ST01-016", "ENTERS_PLAY"): _spec(
        "ST01-016", "ENTERS_PLAY",
        primitive_steps=[{"primitive": "addToHand", "target": "self_shield_top"}],
    ),
    # ST01-016：[Activate/Main]Rest this Base: 全體我方 Link Unit 本回合 AP+1
    ("ST01-016", "ACTIVATE_MAIN"): _spec(
        "ST01-016", "ACTIVATE_MAIN",
        cost={"resources": 0, "rest_source": True},
        primitive_steps=[{
            "primitive": "modifyAP", "target": "self_all_link_unit",
            "amount": 1, "duration": "this_turn",
        }],
    ),
}


class ReferenceSt01Interpreter(EffectInterpreter):
    """以人工 spec 回答的 deterministic interpreter（僅 ST01）。"""

    def __init__(self, dictionary=None):
        dictionary = dictionary or EffectDictionary()
        gate = SpecGate(dictionary)
        self._specs = {}
        for key, spec in _SPECS.items():
            self._specs[key] = gate.validate(deepcopy(spec))

    def interpret(self, card, timing, context=None):
        card_id = card["id"]
        spec = self._specs.get((card_id, timing))
        if spec is not None:
            return deepcopy(spec)
        return {
            "status": "unsupported",
            "source_card_id": card_id,
            "timing": timing,
            "target_requirements": [],
            "primitive_steps": [],
            "unsupported_capabilities": [f"no reference spec for {card_id}@{timing}"],
            "notes": "reference interpreter only covers ST01 effects",
        }
