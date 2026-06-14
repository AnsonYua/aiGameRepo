"""Viewer state builder：raw state → 某玩家可見的 viewer-safe state + markdown。

可見性規則：
- 自己的手牌完整；對手手牌只有張數
- 雙方牌組 / 資源牌組 / 盾牌只有張數
- base / resources / battle_area / trash / removal 公開
- pending choice 只讓決策玩家看到內容；對手只看到「對手正在決策」
- trigger queue 與內部 effect run 不輸出
"""

from __future__ import annotations

from copy import deepcopy


class ViewerStateBuilder:
    def build_for_player(self, state_store, viewer_player):
        viewer_state = self._build_viewer_state(state_store, viewer_player)
        return {
            "viewer_state": viewer_state,
            "markdown": self._build_markdown(viewer_state),
        }

    def _build_viewer_state(self, state_store, viewer_player):
        raw_state = state_store.get_state()
        opponent_player = "P2" if viewer_player == "P1" else "P1"
        return {
            "game_id": raw_state.get("game_id"),
            "viewer_player": viewer_player,
            "opponent_player": opponent_player,
            "turn": raw_state.get("turn"),
            "phase": raw_state.get("phase"),
            "step": raw_state.get("step"),
            "active_player": raw_state.get("active_player"),
            "priority_player": raw_state.get("priority_player"),
            "battle_context": deepcopy(raw_state.get("battle_context")),
            "game_over": raw_state.get("game_over"),
            "winner": raw_state.get("winner"),
            "decision_type": self._detect_decision_type(raw_state, viewer_player),
            "players": {
                viewer_player: self._build_player_block(
                    raw_state["players"][viewer_player], is_viewer=True,
                ),
                opponent_player: self._build_player_block(
                    raw_state["players"][opponent_player], is_viewer=False,
                ),
            },
            "pending_choice": self._build_pending_choice(raw_state, viewer_player),
        }

    def _detect_decision_type(self, raw_state, viewer_player):
        if raw_state.get("game_over"):
            return "game_over"
        pending = raw_state.get("pending_choice") or []
        if pending:
            if pending[0].get("player_id") == viewer_player:
                return "pending_choice"
            return "wait"
        phase = raw_state.get("phase")
        step = raw_state.get("step")
        if raw_state.get("priority_player") == viewer_player and (
            phase == "main"
            or (phase == "battle" and step in {"block", "action"})
            or (phase == "end" and step == "action")
        ):
            return "action"
        return "wait"

    def _build_player_block(self, player_state, is_viewer):
        battle_area = player_state.get("battle_area", [])
        return {
            "player_id": player_state.get("player_id"),
            "hand_count": len(player_state.get("hand", [])),
            "hand": list(player_state.get("hand", [])) if is_viewer else [],
            "deck_count": len(player_state.get("deck", [])),
            "resource_deck_count": player_state.get("resource_deck_count", 0),
            "shield_count": len(player_state.get("shield", [])),
            "resources": deepcopy(player_state.get("resources", {})),
            "base": self._build_base_block(player_state.get("base")),
            "battle_area": [self._build_battle_slot(slot) for slot in battle_area],
            "board_summary": {
                "units": sum(1 for slot in battle_area if slot.get("unit_id") is not None),
                "empty_slots": sum(1 for slot in battle_area if slot.get("unit_id") is None),
                "rested_units": sum(1 for slot in battle_area if slot.get("status") == "rested"),
                "damaged_units": sum(1 for slot in battle_area if slot.get("damage", 0) > 0),
                "blockers": sum(1 for slot in battle_area if "Blocker" in slot.get("keywords", [])),
            },
            "trash": list(player_state.get("trash", [])),
            "removal": list(player_state.get("removal", [])),
        }

    def _build_base_block(self, base):
        if not base or not base.get("alive", True):
            return {
                "present": False, "card_id": None, "ap": 0, "hp": 0,
                "damage": 0, "remaining_hp": 0, "status": None,
            }
        hp = base.get("hp", 0)
        damage = base.get("damage", 0)
        return {
            "present": True,
            "card_id": base.get("card_id"),
            "ap": base.get("ap", 0),
            "hp": hp,
            "damage": damage,
            "remaining_hp": max(hp - damage, 0),
            "status": base.get("status"),
        }

    def _build_battle_slot(self, slot):
        hp = slot.get("hp", 0)
        damage = slot.get("damage", 0)
        return {
            "slot": slot.get("slot"),
            "empty": slot.get("unit_id") is None,
            "unit_id": slot.get("unit_id"),
            "pilot_id": slot.get("pilot_id"),
            "is_link": slot.get("is_link", False),
            "ap": slot.get("ap", 0),
            "hp": hp,
            "damage": damage,
            "remaining_hp": max(hp - damage, 0),
            "status": slot.get("status"),
            "keywords": list(slot.get("keywords", [])),
            "turns_on_field": slot.get("turns_on_field", 0),
        }

    def _build_pending_choice(self, raw_state, viewer_player):
        pending = raw_state.get("pending_choice") or []
        if not pending:
            return {"visible": False, "waiting_player": None, "type": None, "message": None, "options": []}
        choice = pending[0]
        if choice.get("player_id") != viewer_player:
            return {
                "visible": False,
                "waiting_player": choice.get("player_id"),
                "type": None,
                "message": "對手正在決策",
                "options": [],
            }
        return {
            "visible": True,
            "waiting_player": choice.get("player_id"),
            "type": choice.get("type"),
            "message": choice.get("message"),
            "options": [
                {"id": option.get("id"), "label": option.get("label")}
                for option in choice.get("options", [])
            ],
        }

    # ------------------------------------------------------------------
    # markdown
    # ------------------------------------------------------------------

    def _build_markdown(self, viewer_state):
        viewer_player = viewer_state["viewer_player"]
        opponent_player = viewer_state["opponent_player"]
        viewer_block = viewer_state["players"][viewer_player]
        opponent_block = viewer_state["players"][opponent_player]
        sections = [
            "# 對局資訊",
            f"- 你是：{viewer_player}",
            f"- 回合：{viewer_state['turn']}",
            f"- 階段：{viewer_state['phase']} / {self._nullable(viewer_state['step'])}",
            f"- 當前優先權：{self._nullable(viewer_state['priority_player'])}",
            f"- 當前行動玩家：{self._nullable(viewer_state['active_player'])}",
            "",
            "# 我方",
            *self._player_lines(viewer_block, reveal_hand=True),
            "",
            "# 對手",
            *self._player_lines(opponent_block, reveal_hand=False),
            "",
            "# 戰鬥區",
            *self._battle_lines("我方", viewer_block["battle_area"]),
            *self._battle_lines("對手", opponent_block["battle_area"]),
            "",
            "# 當前決策",
            *self._decision_lines(viewer_state),
        ]
        return "\n".join(sections)

    def _player_lines(self, block, reveal_hand):
        lines = [f"- 手牌：{block['hand_count']} 張"]
        if reveal_hand:
            lines.append(f"- 手牌內容：{self._card_list(block['hand'])}")
        lines.extend([
            f"- 牌組：{block['deck_count']} 張",
            f"- 資源牌組：{block['resource_deck_count']} 張",
            f"- 盾牌：{block['shield_count']} 剩餘",
            f"- 基地：{self._base_text(block['base'])}",
            f"- 資源：active {block['resources'].get('active', 0)} / "
            f"rested {block['resources'].get('rested', 0)} / ex {block['resources'].get('ex', 0)}",
            f"- 廢棄區：{self._card_list(block['trash'])}",
        ])
        return lines

    def _battle_lines(self, side_label, battle_area):
        lines = []
        for slot in battle_area:
            if slot["empty"]:
                lines.append(f"- {side_label} {slot['slot']} 號位：空")
                continue
            pilot_text = f" | Pilot：{slot['pilot_id']}" if slot.get("pilot_id") else ""
            link_text = "（Link）" if slot.get("is_link") else ""
            keywords = f" | 關鍵字：{','.join(slot['keywords'])}" if slot.get("keywords") else ""
            lines.append(
                f"- {side_label} {slot['slot']} 號位：{slot['unit_id']}{link_text} | "
                f"AP/HP：{slot['ap']}/{slot['remaining_hp']} | 傷害：{slot['damage']} | "
                f"狀態：{self._nullable(slot['status'])}{pilot_text}{keywords}"
            )
        return lines

    def _decision_lines(self, viewer_state):
        decision_type = viewer_state["decision_type"]
        pending = viewer_state["pending_choice"]
        if decision_type == "game_over":
            return ["- 對局已結束", f"- 勝者：{self._nullable(viewer_state['winner'])}"]
        if decision_type == "pending_choice" and pending["visible"]:
            lines = [f"- 你需要：{pending['message'] or pending['type']}"]
            if pending["options"]:
                lines.append("- options：")
                lines.extend(
                    f"  - `{option['id']}` | {option.get('label')}" for option in pending["options"]
                )
            return lines
        if decision_type == "action":
            return ["- 你需要：一般行動（合法指令見 legal_commands）"]
        if pending["waiting_player"]:
            return [f"- 你需要：等待 {pending['waiting_player']} 決策"]
        return ["- 你需要：等待遊戲狀態推進"]

    def _base_text(self, base):
        if not base["present"]:
            return "無"
        return f"{base['card_id']} | AP|HP：{base['ap']}|{base['remaining_hp']}"

    def _card_list(self, cards):
        if not cards:
            return "無"
        return ", ".join(f"`{card_id}`" for card_id in cards)

    def _nullable(self, value):
        return "無" if value is None else str(value)
