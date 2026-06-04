# UI Templates — 中央文案管理

**所有使用者面向的輸出「必須」使用此處定義的模板，不得自行發想格式。**
修改此處即可全域變更格式，無需修改各 skill。

---

## 1. 狀態標題（每條輸出第一行）

### display_title
`Turn {turn} | {phase}{step} | {active_player}'s turn`

Example: `Turn 1 | pre-game | P1's turn`

### display_mulligan_title
`Mulligan — P1 is first player`

---

## 2. 手牌顯示

### display_hand
格式：
```
Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
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
`Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}`

---

## 4. 戰區顯示

### display_battle_area
格式：
```
Your Battle Area ({occupied_slots}/{total_slots}):
- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}
- Slot{slot}: empty
...

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
- Slot{slot}: Unknown | {if visible show details}
- Slot{slot}: empty
...
```

### display_battle_area_short
Format:
```
Your Battle Area: {occupied_slots} unit(s)
Opponent's Battle Area: {opponent_occupied} unit(s)
```

---

## 5. 防禦層顯示

### display_shields
`Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}`

---

## 6. Priority & Available Actions

### display_priority
`Priority: {priority}{you_suffix}`

### display_actions
Format (list available commands per current phase/step):
When determining play/deploy legality, must check both **Level (CR-3.2)** and **Cost (CR-3.3)**:
- Level = resources.active + resources.rested + resources.ex ≥ card.level
- Cost = resources.active ≥ card.cost (or EX covers difference)
Only ✅ if both satisfied, otherwise ❌.

```
Available:
- pass
- draw                # draw phase
- resource            # resource phase
- play/deploy <card_id>  # main phase (requires Level ≥ Lv and active ≥ Cost)
- attack <slot>       # main phase (if eligible unit)
- block <slot>        # battle (attack step)
- redraw              # pre-game mulligan
- keep                # pre-game mulligan
- activate <slot>     # main phase (if battle_area unit has manual_activate ability)
- pair <card_id> <slot>  # main phase (deploy Pilot to existing unit's slot)
- concede
```
Available:
- pass
- draw                # draw phase
- resource            # resource phase
- play/deploy <card_id>  # main phase（需 Level ≥ Lv 且 active ≥ Cost）
- attack <slot>       # main phase (if eligible unit)
- block <slot>        # battle (attack step)
- activate <slot>     # main phase（battle_area 單位有 manual_activate 能力時可用）
- pair <card_id> <slot>  # main phase（將 Pilot 部署到已有單位的 slot）
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
{display_hand} or {display_hand_short} (active_player's hand only; opponent uses display_opponent_hand)
{display_battle_area} or {display_battle_area_short}
{display_shields}

{latest_battle_log}

{display_priority}

{display_actions}
```

### compose_mulligan
Mulligan phase output (§5 Mulligan Flow step 1):

```
{display_mulligan_title}

Your Hand:
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Enter redraw or keep
```

---

## 8. 特殊事件顯示

### display_phase_transition
Format:
```
--- {phase}{ → {next_phase}} ---
```

### display_damage_result
Format:
```
⚔ {attacker_slot} ({attacker_ap}AP) → {target}
  {target} takes {damage} damage{ / destroyed if hp≤0}
{additional effects like Breach, Burst}
```

### display_game_over
Format:
```
═══════════════════════════
   GAME OVER — {winner} wins
   Reason: {reason} [CR-X.Y]
═══════════════════════════
```

---

## 9. 隱私遮罩（Privacy Gate）

### privacy_mask
- Opponent hand → `"Unknown"`
- Opponent deck → `"{deck_count} cards"` (count only)
- Opponent shields → `"{opponent_shields} remaining"` (count only, no card_id)
- Opponent battle area → `"Slot{slot}: Unknown / empty / AP:?/HP:?"` (known info exceptions apply)

---

## 10. 錯誤訊息

> **Note (P2-20)**: Orchestrator must check phase match before routing to the corresponding display template; if mismatched, emit `err_phase_mismatch`.

### err_phase_mismatch
`requires phase=<X>, current phase=<Y>`

### err_illegal_command
`illegal command: <reason>`

### err_token_play
`Token type (level=0) cannot be played from hand`

### err_insufficient_resources
`insufficient resources: need {N}, have {N}`

### err_invalid_slot
`invalid slot: {slot} (must be 0-5)`

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
`"<active_player> attacks with slot <slot>"`

### log_block
`"<non_active_player> blocks with slot <slot>"`

### log_activate
`"<active_player> activates <effect_id> on <card_id>"`

### log_redraw
`"<player_id> redraws"`

### log_keep
`"<player_id> keeps"`

### log_win
`"<winner> wins by <reason>"`
