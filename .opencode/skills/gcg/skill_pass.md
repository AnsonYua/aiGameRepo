---
name: skill_pass
triggers: [pass, end turn]
phase_lock: any
---

# skill_pass — 讓過與階段推進

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

讓過優先權（CR-2.10）。雙方連續讓過時推進階段/子步驟。

## 依當前階段處理

### main + pass
- 階段 → end，子步驟 → action
- 優先權 → 非行動玩家（CR-2.9）

### main + end turn
- 等同於 `pass`（行為相同）

### battle(action) + pass（單次讓過）
- 單方讓過 → 優先權翻轉給對方（CR-2.10(b)）
- 若雙方已連續讓過 → 進入傷害結算（依 skill_damage.md，orchestrator 在 phase=battle 時載入此參考）
- 優先權 → null（傷害結算後藉 skill_damage 返回 main）

### end(action) + pass（單次讓過）
- 單方讓過 → 優先權翻轉給對方（CR-2.10(b)）
- 若雙方已連續讓過 → 進入清理步驟（CR-2.8）
- 清理（CR-8.1）：手牌 ≥ 11 需棄到 10 張。結束回合，行動玩家切換為對方，turn +1
- 階段 → start，子步驟 → null

### pre-game + pass
- 雙方已完成調度（CR-1.8）
- 委託 `skill_start_phase.md` 統一處理盾牌設置 + 階段推進
- 階段 → start，子步驟 → null，行動玩家不變

### draw + pass
- 抽牌完成 → 推進至資源階段（CR-2.6）
- 此步驟藉 `skill_start_phase.md` 統一處理
- 階段 → resource，子步驟 → null

### resource + pass
- 資源部署完成 → 推進至主要階段（CR-2.7）
- 此步驟藉 `skill_start_phase.md` 統一處理
- 階段 → main，子步驟 → null

### start + pass
- 開始階段自動重置所有橫置卡（CR-2.4）
- 此步驟藉 `skill_start_phase.md` 統一處理
- 階段 → draw，子步驟 → null

### battle(attack) + pass
- 非行動玩家放棄阻擋 → 進入行動子步驟
- 子步驟 → action，優先權 → 非行動玩家（CR-5.12）

### 其他階段 + pass
- 保留處理意外組合（例如 battle/damage + pass）。觸發時記錄為異常。
- 無效果（階段正常繼續）

## 輸出

```yaml
state_diff:
  phase: <next_phase>           # pre-game / start / draw / resource / main / end / battle
  step: <next_step|null>        # action / damage / battle_end / cleanup / null
  turn: +1                      # end(action) cleanup 時
  current_attacker: null        # battle_end 時清除
  p1:                           # 僅 pre-game→start 時設置
    shields: +6                 # 增量（實際 card_ids 由 orchestrator 追蹤）
    deck_count: -6              # 減 6
  p2:                           # 僅 pre-game→start 時設置
    shields: +6
    deck_count: -6
  # ── start→draw 時（CR-2.4）──
  <active_player>:
    resources:
      rested: 0
      active: +<total_rested>
    base:
      status: active             # 僅部署 Base 卡且 alive

  # ── 優先權轉移 ──
  priority: <active_player|non_active_player|null>

  battle_log:                          # 模板見 ui_templates.md §log_pass
    - "<active_player> passes"         # 原始指令為 pass
    # 或
    - "<active_player> ends turn"      # 原始指令為 end turn
```
