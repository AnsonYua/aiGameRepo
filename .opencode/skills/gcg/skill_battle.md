---
name: skill_battle
triggers: [attack]
phase_lock: main
---

# skill_battle — 宣告攻擊

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

宣告攻擊（CR-5）。將階段從 main 轉為 battle(attack)。

## 輸入

- `game_state.md` — 當前狀態
- `slot` — 哪個戰區欄位進行攻擊

## 流程

1. **檢查攻擊資格**（CR-5.4）：
   - 單位必須為直立（status != rested）
   - 單位必須已出場 1+ 回合 或 為 Link Unit（link=true）
2. **檢查是否能攻擊玩家**（從 interpreted effects — 部分單位有此限制）
3. **切換階段/子步驟**：phase=battle, step=attack
4. **記錄攻擊者**：儲存哪個欄位是當前攻擊者（供阻擋/傷害結算）

## 輸出

```yaml
state_diff:
  phase: battle
  step: attack
  current_attacker: <slot>     # 供阻擋/傷害結算追蹤
  priority: null                    # 攻擊宣告階段無優先權窗口
  <active_player>:
    battle_area:
      - slot: <attacking_slot>
        status: rested         # 宣告後攻擊者變為橫置
  battle_log:                          # 模板見 ui_templates.md §log_attack
    - "<active_player> attacks with slot <N>"
```
