---
name: skill_draw
triggers: [draw]
phase_lock: draw
---

# skill_draw

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

Draw phase (CR-2.5). Active player draws 1 card from deck.

## Flow

1. Deck count > 0 → draw 1 card (deck_count -= 1, hand gains 1 card). 從 `.deck_tracking.json` 該玩家的 `library_cards` 頂部取 1 張移至手牌（由 orchestrator 更新）
2. Deck count = 0 → immediate loss (CR-8.2)

## Output

```yaml
state_diff:
  <active_player>:
    hand_cards:
      - add: <card_id>
    deck_count: -1
  battle_log:                          # 模板見 ui_templates.md §log_draw
    - "<active_player> draws a card"
```
