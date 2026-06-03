---
name: skill_start_phase
triggers: [auto_start]
phase_lock: pre-game, start
---

# skill_start_phase

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

全自動推進：從 pre-game（或 start）一口氣推進到 main phase。合併原本 6 次 skill_pass/skill_draw/skill_resource 呼叫，減少 subagent 往返。

## 流程

根據當前 `phase` 決定起點，執行後續所有步驟：

### 起點 = pre-game（Mulligan 完成後）
1. 從各玩家牌庫頂取 6 張設為 shields（deck_count -6, shields +6）。實際 card_id 由 orchestrator 更新 `.deck_tracking.json`
2. Phase → start，step = null

### 起點 = start（或上一步完成後）
3. 重置所有橫置卡（CR-2.4）：`resources.rested → 0, resources.active ← total`；若 base 部署卡且 alive → `base.status: active`
4. Phase → draw

### Draw（強制，CR-2.5）
5. deck_count > 0 → hand +1 card, deck_count -1
6. deck_count = 0 → immediate loss（CR-8.2）
7. Phase → resource

### Resource（強制，CR-2.6）
8. resource_deck_count > 0 → resource_deck_count -1, resources.active +1
9. resource_deck_count = 0 → skip（CR-8.3）
10. Phase → main, step = null, priority = active_player

## 輸出

```yaml
state_diff:
  phase: main
  step: null
  priority: <active_player>
  p1:
    shields: +6           # 僅 pre-game 起點
    deck_count: -6        # 僅 pre-game 起點
    hand_cards:
      - add: <card_id>    # draw 1 card
    deck_count: -1        # draw
    resource_deck_count: -1  # resource
    resources:
      active: +<total_before>  # start→draw untap: rested→active
      rested: 0
  p2:
    shields: +6
    deck_count: -6
  battle_log:         # 模板見 ui_templates.md §log_pass, §log_draw, §log_resource
    - "<active_player> passes"           # start phase
    - "<active_player> draws a card"     # draw
    - "<active_player> deploys a resource"  # resource
    - "<active_player> passes"           # draw→resource
    - "<active_player> passes"           # resource→main
  game_over: false         # unless deck=0 on draw
  winner: null
```
