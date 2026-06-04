---
name: skill_draw
triggers: [draw]
phase_lock: draw
---

# skill_draw — 抽牌階段

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

抽牌階段（CR-2.5）。行動玩家從牌庫抽 1 張牌。

## 流程

1. 牌庫 > 0 → 抽 1 張（deck_count -= 1，手牌 +1）
2. 牌庫 = 0 → 立即敗北（CR-8.2）

## 輸出

```yaml
state_diff:
  <active_player>:
    hand_cards:
      - add: <card_id>
    deck_count: -1
  battle_log:                          # 模板見 ui_templates.md §log_draw
    - "<active_player> draws a card"
```
