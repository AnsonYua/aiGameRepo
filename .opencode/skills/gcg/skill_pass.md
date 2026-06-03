---
name: skill_pass
triggers: [pass, end turn]
phase_lock: any
---

# skill_pass

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

Pass priority (CR-2.10). Advances the game through phases/steps when both players pass.

## Flow by current phase

### main + pass
- Phase → end, step → action
- priority → non-active player（CR-2.9）

### main + end turn
- Alias for `pass` (same behavior)

### battle(action) + pass
- Both passed → damage resolves per skill_damage.md（orchestrator 在 phase=battle 時附加此參考）
- priority → null（damage 解析後將由 skill_damage 設定回 main）

### end(action) + pass
- Both passed → advance to cleanup
- Cleanup: discard if hand ≥11 (CR-8.1), then end turn
- active_player switches, phase → start, priority → new active_player

### pre-game + pass
- 雙方調度（Mulligan）已完成（CR-1.8）
- 從各玩家牌庫頂取 6 張設為 shields，依序：第 1 張（原牌庫頂）→ 盾牌最下層（最內層，FAQ Q8），第 6 張 → 盾牌最上層（最外層，緊鄰 Base）。deck_count 減 6（CR-1.5）
- 實際盾牌卡 ID 記錄於 `.deck_tracking.json`（由 orchestrator 在 §10 更新）
- Phase → start, step → null, 不切換 active_player

### draw + pass
- Draw 完成 → 推進到 Resource Phase（CR-2.6）
- Phase → resource, step → null

### resource + pass
- Resource 完成 → 推進到 Main Phase（CR-2.7）
- Phase → main, step → null

### start + pass
- Start Phase 自動重置所有橫置卡（CR-2.4）：`resources.rested → 0, resources.active ← total, base.status → active`（若 base 部署卡且 alive）
- Phase → draw, step → null

### battle(attack) + pass
- 非 active player 放棄阻擋 → 推進到 action step
- Step → action, priority → active_player（CR-5.12）

### any other phase + pass
- No effect (phase continues normally)

## Output

```yaml
state_diff:
  phase: <next_phase>           # pre-game / start / draw / resource / main / end / battle
  step: <next_step|null>        # action / damage / battle_end / cleanup / null
  current_attacker: null        # cleared on battle_end
  p1:                           # 僅 pre-game→start 時設置
    shields: +6                 # 增量（deck_tracking.json 記錄實際 card_ids）
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

  # ── priority 轉移 ──
  priority: <active_player|non_active_player|null>

  battle_log:                          # 模板見 ui_templates.md §log_pass
    - "<active_player> passes"         # 原始指令為 pass
    # 或
    - "<active_player> ends turn"      # 原始指令為 end turn
```
