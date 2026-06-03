# UI Templates — 中央文案管理

**所有使用者面向的輸出「必須」使用此處定義的模板，不得自行發想格式。**
修改此處即可全域變更格式，無需修改各 skill。

---

## 1. 狀態標題（每條輸出第一行）

### display_title
`Turn {N} | {Phase}{Step} | {active_player}'s turn`

範例：`Turn 1 | pre-game | P1's turn`

### display_mulligan_title
`Mulligan — P1 為先手`

---

## 2. 手牌顯示

### display_hand
格式：
```
Your Hand ({count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}
...
```

### display_hand_short
格式（僅 card_id + name）：
```
Your Hand ({count}): {card_id}({name}), {card_id}({name}), ...
```

### display_opponent_hand
`Opponent's Hand: {count} cards`

---

## 3. 資源顯示

### display_resources
`Resources: active={N}, rested={N}, EX={N} | Deck: {N} | Resource Deck: {N}`

---

## 4. 戰區顯示

### display_battle_area
格式：
```
Your Battle Area ({occupied}/{total}):
- Slot{N}: [{card_id}] {name} | AP:{ap}/HP:{hp-hp-damage} | {pilot_id} | {keywords} | {status}
- Slot{N}: empty
...

Opponent's Battle Area ({occupied}/{total}):
- Slot{N}: Unknown | {if visible show details}
- Slot{N}: empty
...
```

### display_battle_area_short
格式：
```
Your Battle Area: {count} unit(s)
Opponent's Battle Area: {count} unit(s)
```

---

## 5. 防禦層顯示

### display_shields
`Shields: {N} remaining | Base: {card_id} | HP: {current}/{max}`

---

## 6. 優先權與可用行動

### display_priority
`Priority: {player}`

### display_actions
格式（依 current phase/step 列出可用指令）：
```
Available:
- pass
- draw                # draw phase
- resource            # resource phase
- play/deploy <card_id>  # main phase
- attack <slot>       # main phase (if eligible unit)
- block <slot>        # battle (attack step)
- redraw              # pre-game mulligan
- keep                # pre-game mulligan
- concede
```

---

## 7. 完整輸出模板（Orchestrator 輸出時合成）

### compose_state
Orchestrator 每次回傳給使用者時，依以下順序組合：

```
{display_title}
{display_resources}
{display_hand} 或 {display_hand_short}（僅 active_player 的手牌；opponent 用 display_opponent_hand）
{display_battle_area} 或 {display_battle_area_short}
{display_shields}

{battle_log 最新一筆}

Priority: {player}

{display_actions}
```

### compose_mulligan
Mulligan 階段專用輸出（§5 Mulligan Flow 第 1 步）：

```
{display_mulligan_title}

Your Hand:
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}
...

請輸入 redraw 或 keep
```

---

## 8. 特殊事件顯示

### display_phase_transition
格式：
```
--- {Phase}{ → {next_phase}} ---
```

### display_damage_result
格式：
```
⚔ {attacker_slot} ({attacker_ap}AP) → {target}
  {target} takes {N} damage{ / destroyed if hp≤0}
{additional effects like Breach, Burst}
```

### display_game_over
格式：
```
═══════════════════════════
   GAME OVER — {winner} 勝利
   原因：{reason} [CR-X.Y]
═══════════════════════════
```

---

## 9. 隱私遮罩（Privacy Gate）

### privacy_mask
- 對手手牌 → `"Unknown"`
- 對手牌庫 → `"{count} cards"`（僅張數）
- 對手盾牌 → `"{count} remaining"`（僅張數，不含 card_id）
- 對手戰區 → `"Slot{N}: Unknown / empty / AP:?/HP:?"`（已知資訊例外）

---

## 10. 錯誤訊息

### err_phase_mismatch
`requires phase=<X>, current phase=<Y>`

### err_illegal_command
`illegal command: <reason>`

### err_token_play
`Token type (level=0) cannot be played from hand`

### err_insufficient_resources
`insufficient resources: need {N}, have {N}`

### err_invalid_slot
`invalid slot: {N} (must be 0-5)`

---

## 11. Judge Verdicts（裁判判定 — 內部使用）

### judge_accept
`accept`

### judge_reject
`reject: <reason> [CR-X.Y]`

---

## 12. Battle Log（戰鬥記錄 — 寫入 game_state.battle_log[]）

### log_initialize
`"<player> started game as first player [CR-1.1]"`

### log_pass
`"<active_player> passes"` / `"<active_player> ends turn"`

### log_damage
`"<attacker> deals <N> damage to <target>"`

### log_draw
`"<active_player> draws a card"`

### log_resource
`"<active_player> deploys a resource"`

### log_play_card
`"<active_player> plays/deploys/pairs <card_id>"`

### log_attack
`"<active_player> attacks with slot <N>"`

### log_block
`"<non_active_player> blocks with slot <N>"`

### log_activate
`"<active_player> activates <effect_id> on <card_id>"`

### log_redraw
`"<player_id> redraws"`

### log_keep
`"<player_id> keeps"`

### log_win
`"<winner> wins by <reason>"`
