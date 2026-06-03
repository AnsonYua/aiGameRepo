---
name: skill_redraw
triggers: [redraw, mulligan, keep]
phase_lock: pre-game
---

# skill_redraw

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

Mulligan / redraw (CR-1.8). 每次調用處理一個玩家的決定。P1 先決定，然後 P2。

## Input

- `game_state.md` — current pre-game state (5 cards in hand)
- `player_id` — who called redraw (P1|P2)
- `action` — `redraw` 或 `keep`

## Flow

1. 若 `action=keep`：僅記錄玩家保留手牌，不回牌庫
2. 若 `action=redraw`：將整副手牌放回牌庫底 → 抽 5 張新牌（從牌庫頂）→ 洗牌。牌庫總數不變（CR-1.8／FAQ Q10）。`.deck_tracking.json` 中的 `library_cards` 需重新洗牌（由 orchestrator 更新）
3. 每位玩家最多只能 redraw 一次

## Output

```yaml
state_diff:
  <player_id>:
    hand_cards: [<5 new card_ids>]   # 僅 redraw 時變更；keep 時不變
    deck_count: <unchanged>          # 總數不變（放回又抽出）
  battle_log:                          # 模板見 ui_templates.md §log_redraw / §log_keep
    - "<player_id> redraws"
```
