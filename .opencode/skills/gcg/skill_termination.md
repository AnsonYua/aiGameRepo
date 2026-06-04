---
name: skill_termination
triggers: [concede]
phase_lock: any
---

# skill_termination — 遊戲結束

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

終止遊戲（CR-9）。設定 game_over=true 並宣告勝者。

## 觸發條件

- `concede` 指令 → 投降方立即敗北（CR-8.4）
- Orchestrator 偵測敗北（CR-4.9：無盾牌 + 直擊，CR-8.2：牌庫空 + 需抽牌）

## 流程

1. 判定敗者：
   - 投降方 → 敗者（CR-8.4）
   - 無盾牌 + 直接傷害 → 敗者（CR-4.9）
   - 牌庫空 + 需抽牌 → 敗者（CR-8.2）
2. 勝者 = 另一方
3. 設定 game_over=true、winner、phase=null、step=null

## 輸出

```yaml
state_diff:
  phase: null
  step: null
  game_over: true
  winner: P1|P2
  battle_log:                          # 模板見 ui_templates.md §log_win
    - "<winner> wins by <reason>"
```
