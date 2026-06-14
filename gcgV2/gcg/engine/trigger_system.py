"""Trigger detection and queue management.

偵測（deterministic，靠 RulesIndex）→ 入 queue → runtime resolve loop 逐一
交給 interpreter 解讀並執行。queue 順序固定：事件發生順序 FIFO。
"""

from __future__ import annotations


def make_trigger(timing, controller, card_id, source_slot=None, source_zone="battle_area", after_default=None):
    return {
        "timing": timing,
        "controller": controller,
        "card_id": card_id,
        "source_slot": source_slot,
        "source_zone": source_zone,
        # trigger 結算後來源卡的預設去向（例如 burst 卡未被效果移動 → trash）
        "after_default": after_default,
    }


class TriggerSystem:
    def __init__(self, state_store, rules_index):
        self.state = state_store
        self.rules_index = rules_index

    # ------------------------------------------------------------------
    # detection from events
    # ------------------------------------------------------------------

    def detect_for_event(self, event):
        """把一個 engine 事件轉成 0..n 個 trigger context。"""
        event_type = event.get("type")
        if event_type == "unit_deployed":
            return self._unit_enters_play(event)
        if event_type == "base_deployed":
            return self._base_enters_play(event)
        if event_type == "pairing_complete":
            return self._pairing_complete(event)
        if event_type == "attack_declared":
            return self._attack_declared(event)
        if event_type == "unit_destroyed":
            return self._unit_destroyed(event)
        if event_type == "shield_broken":
            return self._shield_broken(event)
        return []

    def detect_end_of_turn(self, active_player):
        """回合結束觸發（例如 <Repair>），只看 active player 的場面。"""
        triggers = []
        for slot in self.state.iter_units(active_player):
            if self.rules_index.has_trigger(slot["unit_id"], "END_OF_TURN"):
                triggers.append(make_trigger(
                    timing="END_OF_TURN",
                    controller=active_player,
                    card_id=slot["unit_id"],
                    source_slot=slot["slot"],
                ))
        return triggers

    # ------------------------------------------------------------------

    def _unit_enters_play(self, event):
        card_id = event["card_id"]
        if not self.rules_index.has_trigger(card_id, "ENTERS_PLAY"):
            return []
        return [make_trigger(
            timing="ENTERS_PLAY",
            controller=event["player"],
            card_id=card_id,
            source_slot=event["slot"],
        )]

    def _base_enters_play(self, event):
        card_id = event["card_id"]
        if not self.rules_index.has_trigger(card_id, "ENTERS_PLAY"):
            return []
        return [make_trigger(
            timing="ENTERS_PLAY",
            controller=event["player"],
            card_id=card_id,
            source_zone="base",
        )]

    def _pairing_complete(self, event):
        triggers = []
        slot_index = event["slot"]
        player = event["player"]
        unit_id = event.get("unit_id")
        pilot_id = event.get("pilot_id")
        # [When Paired] 可能寫在 Unit 卡或 Pilot 卡上
        if unit_id and self.rules_index.has_trigger(unit_id, "PAIRING_COMPLETE"):
            triggers.append(make_trigger(
                timing="PAIRING_COMPLETE",
                controller=player,
                card_id=unit_id,
                source_slot=slot_index,
            ))
        if pilot_id and self.rules_index.has_trigger(pilot_id, "PAIRING_COMPLETE"):
            triggers.append(make_trigger(
                timing="PAIRING_COMPLETE",
                controller=player,
                card_id=pilot_id,
                source_slot=slot_index,
            ))
        return triggers

    def _attack_declared(self, event):
        triggers = []
        player = event["player"]
        slot_index = event["slot"]
        slot = self.state.get_slot(player, slot_index)
        unit_id = slot.get("unit_id")
        pilot_id = slot.get("pilot_id")
        if unit_id and self.rules_index.has_trigger(unit_id, "ATTACK_PHASE"):
            triggers.append(make_trigger(
                timing="ATTACK_PHASE",
                controller=player,
                card_id=unit_id,
                source_slot=slot_index,
            ))
        if pilot_id and self.rules_index.has_trigger(pilot_id, "ATTACK_PHASE"):
            triggers.append(make_trigger(
                timing="ATTACK_PHASE",
                controller=player,
                card_id=pilot_id,
                source_slot=slot_index,
            ))
        return triggers

    def _unit_destroyed(self, event):
        card_id = event["card_id"]
        if not self.rules_index.has_trigger(card_id, "DESTROYED"):
            return []
        return [make_trigger(
            timing="DESTROYED",
            controller=event["player"],
            card_id=card_id,
            source_slot=None,
            source_zone="trash",
        )]

    def _shield_broken(self, event):
        """盾牌破壞：有 [Burst] → burst trigger；否則由 runtime 直接進廢棄區。"""
        card_id = event["card_id"]
        if not self.rules_index.has_trigger(card_id, "BURST_CONDITION"):
            return []
        return [make_trigger(
            timing="BURST_CONDITION",
            controller=event["player"],
            card_id=card_id,
            source_zone="burst",
            after_default="trash",
        )]

    # ------------------------------------------------------------------
    # queue helpers
    # ------------------------------------------------------------------

    def enqueue_all(self, triggers):
        for trigger in triggers:
            self.state.enqueue_trigger(trigger)

    def has_waiting_trigger(self):
        return self.state.has_trigger()

    def pop_next_trigger(self):
        return self.state.pop_next_trigger()
