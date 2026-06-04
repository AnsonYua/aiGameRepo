---
name: skill_block
triggers: [block]
phase_lock: battle
---

# skill_block — 阻擋

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

宣告阻擋者（CR-5.8, CR-6.1）。非行動玩家攔截攻擊。

## 輸入

- `game_state.md` — 當前狀態
- `slot` — 哪個戰區欄位進行阻擋

## 流程

1. **檢查階段/子步驟**：phase 必須為 battle，step 必須為 attack
2. **讀取 current_attacker**：`game_state.current_attacker` 中的欄位正在被阻擋
3. **檢查阻擋資格**：
   - 單位必須具有 Blocker 關鍵字（CR-6.1）
   - 單位必須為直立（status != rested）
   - 單位必須屬於非行動玩家
4. **執行阻擋**：橫置阻擋者（CR-5.8）
5. **轉向**：攻擊現在指向阻擋者而非防禦層（CR-5.9）
6. **推進子步驟**：子步驟 → action，優先權 → 非行動玩家（CR-5.12 / CR-2.10(a)）

## 輸出

```yaml
state_diff:
  step: action                  # 推進至 action 子步驟（CR-5.12）
  priority: <non_active_player>     # 非行動玩家優先取得優先權（CR-5.12）
  <non_active_player>:
    battle_area:
      - slot: <blocking_slot>
        status: rested          # 阻擋者變為橫置
  battle_log:                          # 模板見 ui_templates.md §log_block
    - "<non_active_player> blocks with slot <N>"
```
