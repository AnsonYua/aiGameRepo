---
name: skill_redraw
triggers: [redraw, mulligan, keep]
phase_lock: pre-game
---

# skill_redraw — 調度（重抽）

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

調度 / 重抽（CR-1.8）。每次呼叫處理一位玩家的決定。P1 先決定，接著 P2。

## 輸入

- `game_state.md` — 當前 pre-game 狀態（手牌 5 張）
- `player_id` — 誰呼叫了 redraw（P1|P2）
- `action` — `redraw` 或 `keep`

## 流程

1. 若 `action=keep`：記錄玩家保留手牌，不操作牌庫
2. 若 `action=redraw`：將整副手牌放回牌庫底 → 抽 5 張新牌（從牌庫頂）→ 洗牌。牌庫總數不變（CR-1.8 / FAQ Q10）
3. 每位玩家最多重抽一次

## 輸出

```yaml
state_diff:
  <player_id>:
    hand_cards: [<5 new card_ids>]   # 僅 redraw 時變更；keep 時不變
    deck_count: <unchanged>          # 總數不變（放回又抽出）
  battle_log:                          # 模板見 ui_templates.md §log_redraw / §log_keep
    - "<player_id> redraws"
```
