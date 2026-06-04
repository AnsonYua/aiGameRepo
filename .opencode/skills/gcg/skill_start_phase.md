---
name: skill_start_phase
triggers: [auto_start]
phase_lock: pre-game, start
---

# skill_start_phase — 自動階段推進

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

全自動推進：從 pre-game（或 start）直達主要階段。合併原本需要 6 次 skill_pass/skill_draw/skill_resource 呼叫的流程，減少子代理往返。

## 流程

起點依當前 `phase` 決定，然後依序執行後續步驟：

### 起點 = pre-game（調度完成後）
1. 從雙方牌庫頂各取 6 張作為盾牌（deck_count -6, shields +6）。實際 card_id 由 orchestrator 透過 state_diff 追蹤
2. 階段 → start，子步驟 = null

### 起點 = start（或前一步驟完成後）
3. 重置所有橫置卡（CR-2.4）：`resources.rested → 0, resources.active ← total`；若 Base 為已部署卡且 alive → `base.status: active`
4. 階段 → draw

### 抽牌（強制，CR-2.5）
5. deck_count > 0 → hand +1 張，deck_count -1
6. deck_count = 0 → 立即敗北（CR-8.2）
7. 階段 → resource

### 資源（強制，CR-2.6）
8. resource_deck_count > 0 → resource_deck_count -1, resources.active +1
9. resource_deck_count = 0 → 跳過（CR-8.3）
10. 階段 → main，子步驟 = null，優先權 = active_player

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
      - add: <card_id>    # 抽 1 張
    deck_count: -1        # 抽牌
    resource_deck_count: -1  # 資源
    resources:
      active: +<total_before>  # start→draw 重置：rested→active
      rested: 0
  p2:
    shields: +6
    deck_count: -6
  battle_log:         # 模板參考：ui_templates.md §log_pass, §log_draw, §log_resource
    - "<active_player> passes"           # 開始階段
    - "<active_player> draws a card"     # 抽牌
    - "<active_player> deploys a resource"  # 資源
    - "<active_player> passes"           # draw→resource
    - "<active_player> passes"           # resource→main
  game_over: false         # 除非抽牌時牌庫為空
  winner: null
```
