"""
# Viewer State Builder Spec

`ViewerStateBuilder` 負責把 `StateStore` 持有的真實遊戲狀態，轉成某位玩家可見的
viewer-safe state 與 markdown。

這個模組是 data-facing layer，不負責：

- 詢問 AI 決策
- 解析 command grammar
- 驗證指令是否合法
- 修改真實 state

## Design Goal

輸出必須同時滿足兩個用途：

1. 給程式使用的 `viewer_state` dict
2. 給上層 prompt builder 或 debug 直接閱讀的 `markdown`

## Public API

外部只應呼叫一個 function：

```python
viewer_state_builder = ViewerStateBuilder()
bundle = viewer_state_builder.build_for_player(
    state_store=state_store,
    viewer_player="P1",
)
```

回傳格式：

```yaml
viewer_state:
  ...
markdown: |
  # 對局資訊
  ...
```

外部不應直接依賴 internal helper。若需要給 AI 用的資料，請直接使用
`build_for_player(...)` 的回傳值。

為了降低整合成本，`viewer_state` 應盡量接近現有 raw state shape，
但必須移除或轉換所有非公開資訊。

## Visibility Rules

- `viewer_player` 自己的 `hand`：完整顯示 card ids 與順序
- 對手 `hand`：隱藏內容，只保留 `hand_count`
- 雙方 `deck`：隱藏內容與順序，只保留 `deck_count`
- 雙方 `resource_deck`：隱藏內容與順序，只保留 `resource_deck_count`
- 雙方 `shield`：隱藏內容與順序，只保留 `shield_count`
- 雙方 `base`：完整公開
- 雙方 `resources`：完整公開
- 雙方 `battle_area`：完整公開
- 雙方 `trash`：完整公開
- 雙方 `removal`：預設完整公開
- `pending_choice`：只讓當前決策玩家看到完整內容；非決策玩家只能看到「對手正在決策」
- `trigger_queue`、internal refs、debug metadata、hidden ordering：不輸出

## Output Spec

Top-level 欄位：

```yaml
game_id: string
viewer_player: P1|P2
opponent_player: P1|P2
turn: int
phase: string
step: string
active_player: P1|P2|null
priority_player: P1|P2|null
game_over: bool
winner: P1|P2|null
decision_type: action|pending_choice|wait|game_over
players:
  P1: <viewer-safe player block>
  P2: <viewer-safe player block>
pending_choice:
  visible: bool
  waiting_player: P1|P2|null
  type: string|null
  message: string|null
  options: []
  prompt_hint: string|null
action_context:
  can_act: bool
  acting_player: P1|P2|null
  notes: [string, ...]
```

Player block 欄位：

```yaml
player_id: P1|P2
hand_count: int
hand: [] | [card_id, ...]
deck_count: int
resource_deck_count: int
shield_count: int
resources:
  active: int
  rested: int
  ex: int
base:
  present: bool
  card_id: string|null
  ap: int
  hp: int
  damage: int
  remaining_hp: int
  status: string|null
battle_area:
  - slot: int
    empty: bool
    unit_id: string|null
    pilot_id: string|null
    ap: int
    hp: int
    damage: int
    remaining_hp: int
    status: string|null
    keywords: [string, ...]
    link: bool
    turns_on_field: int
board_summary:
  units: int
  empty_slots: int
  rested_units: int
  damaged_units: int
  blockers: int
trash: [card_id, ...]
removal: [card_id, ...]
```

## Markdown Spec

`build_markdown(viewer_state)` 輸出固定五段：

1. `# 對局資訊`
2. `# 我方`
3. `# 對手`
4. `# 戰鬥區`
5. `# 當前決策`

範例：

```md
# 對局資訊
- 你是：P1
- 回合：1
- 階段：main / start
- 當前優先權：P1
- 當前行動玩家：P1

# 我方
- 手牌：2 張
- 手牌內容：`ST01-008`, `ST01-012`
- 牌組：37 張
- 能源牌組：8 張
- 護盾：6
- 基地：EX-BASE | AP|HP：0|3
- 能源：active 2 / rested 0 / ex 0
- 廢棄區：`ST01-003`, `ST01-010`
- 除外區：無

# 對手
- 手牌：3 張
- 牌組：35 張
- 能源牌組：7 張
- 護盾：5
- 基地：EX-BASE | AP|HP：0|2
- 能源：active 1 / rested 1 / ex 1
- 廢棄區：`GD01-002`
- 除外區：無

# 戰鬥區
- 我方 0 號位：ST01-001 | AP/HP：2/2 | 傷害：0 | 狀態：active
- 我方 1 號位：空
- 對手 0 號位：GD01-001 | AP/HP：3/3 | 傷害：1 | 狀態：rested
- 對手 1 號位：空

# 當前決策
- 你需要：一般行動
- 目前可由上層 prompt builder 補充合法輸出格式
```

如果 queue head 是 viewer 自己的 pending choice，最後一段需改為列出 options。
"""

from copy import deepcopy


class ViewerStateBuilder:
    """
    # ViewerStateBuilder

    `ViewerStateBuilder` 是 raw state 與上層 AI/prompt 系統之間的唯一可見性轉換層。

    它做三件事：

    1. 從 `StateStore` 取出當前 state
    2. 依 `viewer_player` 移除或轉換非公開資訊
    3. 產生 `viewer_state` 與 `markdown`

    建議整合方式：

    ```python
    bundle = viewer_state_builder.build_for_player(
        state_store=state_store,
        viewer_player="P1",
    )
    ```

    改進方向：

    - 將可見性規則集中在單一 helper，避免散落在多個 if/else
    - 對外只保留一個 public entrypoint
    - state filtering 與 markdown rendering 放在 private helper
    - 保持輸出 schema 穩定，避免上層 prompt 與 parser 一起漂移
    - 不在這個 class 內定義 command grammar；那是 prompt builder / parser 的責任
    """

    def build_for_player(self, state_store, viewer_player):
        """
        Public entrypoint.

        Return both viewer-safe state and markdown for one player's view.
        """
        viewer_state = self._build_viewer_state(state_store, viewer_player)
        return {
            "viewer_state": viewer_state,
            "markdown": self._build_markdown(viewer_state),
        }

    def _build_viewer_state(self, state_store, viewer_player):
        """
        Return a viewer-safe state dict for one player.

        This is a spec-first filtering implementation. It copies the raw state,
        injects viewer metadata, and removes hidden-zone contents from the
        opposing side.
        """
        raw_state = deepcopy(state_store.get_state())
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
            "game_over": raw_state.get("game_over"),
            "winner": raw_state.get("winner"),
            "decision_type": self._detect_decision_type(raw_state, viewer_player),
            "players": self._build_players_block(raw_state, viewer_player, opponent_player),
            "pending_choice": self._build_pending_choice(raw_state, viewer_player),
            "action_context": self._build_action_context(raw_state, viewer_player),
        }

    def _build_markdown(self, viewer_state):
        """
        Render a stable markdown summary from a viewer-safe state.
        """
        viewer_player = viewer_state["viewer_player"]
        opponent_player = viewer_state["opponent_player"]
        viewer_block = viewer_state["players"][viewer_player]
        opponent_block = viewer_state["players"][opponent_player]

        sections = [
            "# 對局資訊",
            f"- 你是：{viewer_player}",
            f"- 回合：{viewer_state['turn']}",
            f"- 階段：{viewer_state['phase']} / {viewer_state['step']}",
            f"- 當前優先權：{self._format_nullable(viewer_state['priority_player'])}",
            f"- 當前行動玩家：{self._format_nullable(viewer_state['active_player'])}",
            "",
            "# 我方",
            *self._build_player_markdown_lines(viewer_block, reveal_hand=True),
            "",
            "# 對手",
            *self._build_player_markdown_lines(opponent_block, reveal_hand=False),
            "",
            "# 戰鬥區",
            *self._build_battle_area_lines("我方", viewer_block["battle_area"]),
            *self._build_battle_area_lines("對手", opponent_block["battle_area"]),
            "",
            "# 當前決策",
            *self._build_decision_lines(viewer_state),
        ]
        return "\n".join(sections)

    def _detect_decision_type(self, raw_state, viewer_player):
        if raw_state.get("game_over"):
            return "game_over"
        pending_choice = self._peek_pending_choice(raw_state)
        if pending_choice is not None:
            if pending_choice.get("player_id") == viewer_player:
                return "pending_choice"
            return "wait"
        if raw_state.get("priority_player") == viewer_player and raw_state.get("phase") in {
            "main",
            "action",
            "battle/action",
        }:
            return "action"
        return "wait"

    def _build_players_block(self, raw_state, viewer_player, opponent_player):
        players = raw_state.get("players", {})
        return {
            viewer_player: self._build_player_block(
                players.get(viewer_player, {}),
                is_viewer=True,
            ),
            opponent_player: self._build_player_block(
                players.get(opponent_player, {}),
                is_viewer=False,
            ),
        }

    def _build_player_block(self, player_state, is_viewer):
        hand = list(player_state.get("hand", [])) if is_viewer else []
        deck = player_state.get("deck", [])
        resource_deck = player_state.get("resource_deck", [])
        shield = player_state.get("shield", [])
        base = player_state.get("base")
        battle_area = player_state.get("battle_area", [])
        return {
            "player_id": player_state.get("player_id"),
            "hand_count": len(player_state.get("hand", [])),
            "hand": hand,
            "deck_count": len(deck),
            "resource_deck_count": len(resource_deck),
            "shield_count": len(shield),
            "resources": deepcopy(player_state.get("resources", {})),
            "base": self._build_base_block(base),
            "battle_area": [self._build_battle_slot(slot) for slot in battle_area],
            "board_summary": self._build_board_summary(battle_area),
            "trash": list(player_state.get("trash", [])),
            "removal": list(player_state.get("removal", [])),
        }

    def _build_base_block(self, base):
        if not base:
            return {
                "present": False,
                "card_id": None,
                "ap": 0,
                "hp": 0,
                "damage": 0,
                "remaining_hp": 0,
                "status": None,
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
            "ap": slot.get("ap", 0),
            "hp": hp,
            "damage": damage,
            "remaining_hp": max(hp - damage, 0),
            "status": slot.get("status"),
            "keywords": list(slot.get("keywords", [])),
            "link": slot.get("link", False),
            "turns_on_field": slot.get("turns_on_field", 0),
        }

    def _build_board_summary(self, battle_area):
        return {
            "units": sum(1 for slot in battle_area if slot.get("unit_id") is not None),
            "empty_slots": sum(1 for slot in battle_area if slot.get("unit_id") is None),
            "rested_units": sum(1 for slot in battle_area if slot.get("status") == "rested"),
            "damaged_units": sum(1 for slot in battle_area if slot.get("damage", 0) > 0),
            "blockers": sum(1 for slot in battle_area if "Blocker" in slot.get("keywords", [])),
        }

    def _build_pending_choice(self, raw_state, viewer_player):
        choice = self._peek_pending_choice(raw_state)
        if choice is None:
            return {
                "visible": False,
                "waiting_player": None,
                "type": None,
                "message": None,
                "options": [],
                "prompt_hint": None,
            }
        if choice.get("player_id") != viewer_player:
            return {
                "visible": False,
                "waiting_player": choice.get("player_id"),
                "type": None,
                "message": "對手正在決策",
                "options": [],
                "prompt_hint": None,
            }
        return {
            "visible": True,
            "waiting_player": choice.get("player_id"),
            "type": choice.get("type"),
            "message": choice.get("message"),
            "options": self._sanitize_pending_choice_options(
                choice.get("options", []),
                viewer_player=viewer_player,
            ),
            "prompt_hint": "請只輸出一個合法指令。",
        }

    def _build_action_context(self, raw_state, viewer_player):
        can_act = raw_state.get("priority_player") == viewer_player and raw_state.get("phase") in {
            "main",
            "action",
            "battle/action",
        }
        return {
            "can_act": can_act,
            "acting_player": raw_state.get("priority_player") if can_act else None,
            "notes": [],
        }

    def _peek_pending_choice(self, raw_state):
        pending_choices = raw_state.get("pending_choice", [])
        if pending_choices:
            return pending_choices[0]
        return None

    def _build_player_markdown_lines(self, player_block, reveal_hand):
        hand_line = f"- 手牌：{player_block['hand_count']} 張"
        lines = [
            hand_line,
        ]
        if reveal_hand:
            lines.append(
                f"- 手牌內容：{self._format_card_list(player_block['hand'])}"
            )
        lines.extend(
            [
                f"- 牌組：{player_block['deck_count']} 張",
                f"- 能源牌組：{player_block['resource_deck_count']} 張",
                f"- 護盾：{player_block['shield_count']}",
                f"- 基地：{self._format_base(player_block['base'])}",
                f"- 能源：{self._format_resources(player_block['resources'])}",
                f"- 廢棄區：{self._format_card_list(player_block['trash'])}",
                f"- 除外區：{self._format_card_list(player_block['removal'])}",
            ]
        )
        return lines

    def _build_battle_area_lines(self, side_label, battle_area):
        if not battle_area:
            return [f"- {side_label}：無"]
        lines = []
        for slot in battle_area:
            if slot["empty"]:
                lines.append(f"- {side_label} {slot['slot']} 號位：空")
                continue
            lines.append(
                f"- {side_label} {slot['slot']} 號位："
                f"{slot['unit_id']} | AP/HP：{slot['ap']}/{slot['remaining_hp']} | "
                f"傷害：{slot['damage']} | 狀態：{self._format_nullable(slot['status'])}"
            )
        return lines

    def _build_decision_lines(self, viewer_state):
        decision_type = viewer_state["decision_type"]
        pending_choice = viewer_state["pending_choice"]
        action_context = viewer_state["action_context"]

        if decision_type == "game_over":
            return [
                "- 你需要：對局已結束",
                f"- 勝者：{self._format_nullable(viewer_state['winner'])}",
            ]

        if decision_type == "pending_choice" and pending_choice["visible"]:
            lines = [
                f"- 你需要：{pending_choice['message'] or pending_choice['type']}",
                f"- choice 類型：{self._format_nullable(pending_choice['type'])}",
            ]
            if pending_choice["options"]:
                lines.append("- options：")
                lines.extend(
                    f"  - {self._format_pending_choice_option(option)}"
                    for option in pending_choice["options"]
                )
            if pending_choice["prompt_hint"]:
                lines.append(f"- 提示：{pending_choice['prompt_hint']}")
            return lines

        if decision_type == "action" and action_context["can_act"]:
            return [
                "- 你需要：一般行動",
                f"- 當前行動玩家：{action_context['acting_player']}",
                "- 目前可由上層 prompt builder 補充合法輸出格式",
            ]

        if pending_choice["waiting_player"] is not None:
            return [f"- 你需要：等待 {pending_choice['waiting_player']} 決策"]

        return ["- 你需要：等待遊戲狀態推進"]

    def _sanitize_pending_choice_options(self, options, viewer_player):
        return [
            self._sanitize_pending_choice_option(option, viewer_player)
            for option in deepcopy(options)
        ]

    def _sanitize_pending_choice_option(self, option, viewer_player):
        if isinstance(option, list):
            return [
                self._sanitize_pending_choice_option(item, viewer_player)
                for item in option
            ]

        if not isinstance(option, dict):
            return option

        sanitized = {}
        option_owner = option.get("player_id") or option.get("owner")
        zone = option.get("zone")
        hidden_zone = zone in {"hand", "deck", "resource_deck", "shield"}
        hidden_from_viewer = hidden_zone and option_owner not in {None, viewer_player}

        for key, value in option.items():
            if key in {"hand", "deck", "resource_deck", "shield"}:
                continue
            if hidden_from_viewer and key in {
                "card_id",
                "card_ids",
                "cards",
                "hand_index",
                "deck_index",
                "shield_index",
            }:
                continue
            sanitized[key] = self._sanitize_pending_choice_option(value, viewer_player)

        return sanitized

    def _format_card_list(self, cards):
        if not cards:
            return "無"
        return ", ".join(f"`{card_id}`" for card_id in cards)

    def _format_resources(self, resources):
        return (
            f"active {resources.get('active', 0)} / "
            f"rested {resources.get('rested', 0)} / "
            f"ex {resources.get('ex', 0)}"
        )

    def _format_base(self, base):
        if not base["present"]:
            return "無"
        return (
            f"{base['card_id']} | AP|HP：{base['ap']}|{base['remaining_hp']}"
        )

    def _format_pending_choice_option(self, option):
        if isinstance(option, dict):
            label = option.get("label")
            option_id = option.get("id")
            if label and option_id:
                return f"`{option_id}` | {label}"
            if label:
                return str(label)
            if option_id:
                return f"`{option_id}`"
            return str(option)
        return str(option)

    def _format_nullable(self, value):
        if value is None:
            return "無"
        return str(value)
