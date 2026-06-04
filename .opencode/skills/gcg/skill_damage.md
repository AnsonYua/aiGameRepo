---
name: skill_damage
phase_lock: battle
note: 非獨立路由 — 與 skill_pass.md 一同載入（phase=battle 時）
---

# skill_damage — 傷害結算

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

傷害結算參考（CR-5.2, CR-5.3）。Orchestrator 在 phase=battle 時將此文件與 `skill_pass.md` 一同載入。非獨立路由。

## 流程

1. 讀取 `current_attacker` 欄位，在 `active_player.battle_area` 中找到攻擊者
2. 檢查是否被阻擋：`non_active_player.battle_area` 有無 status=rested 的欄位（阻擋宣告後）
3. **若有阻擋**：攻擊者以 AP 對阻擋者造成傷害，阻擋者以其 AP 對攻擊者造成傷害。除非有 First Strike（CR-5.7）否則同時結算：FS 方先造成傷害；若目標被破壞則不回擊
4. **若無阻擋**：傷害依 CR-4.3 打到防禦層：
   - 有 Base + 有盾牌 → 傷害到 Base（base.damage += 攻擊者 AP, CR-4.4）
   - 無 Base + 有盾牌 → 傷害到最上層盾牌（盾牌破壞，檢查 Burst CR-6.5）
   - 無盾牌 → 直擊 → 非行動玩家敗北（CR-4.9）
5. **Breach（突破，CR-6.3）**：額外傷害 = 攻擊者的 Breach 值，打到盾牌區（目標判定同 CR-4.3）。Breach 無論阻擋/交換結果皆發動（FAQ Q55）。盾牌區無卡時 Breach 不發動（FAQ Q54）
6. **0 AP 攻擊者**：無法破壞任何防禦層（CR-4.8），若有 Breach 仍適用
7. **檢查破壞**：單位/Base damage ≥ HP 即破壞（從戰區移至 trash，或 base.alive=false）。代幣→移除區（CR-6.7）
8. **Burst（爆發，CR-6.5）**：若被破壞的盾牌中有 Burst 卡，擁有者可選擇觸發。記錄在 `active_effects` 待結算。shields: -N 表示數量；實際 card_id 由 orchestrator 透過 state_diff 追蹤
- 然後：子步驟 → battle_end。若無待處理 Burst → 清除 current_attacker → 返回 main（CR-5.3）

## 輸出

```yaml
state_diff:
  step: battle_end / null        # null 若無 burst → 返回 main
  current_attacker: null         # 清除
  <active_player>:               # 攻擊方
    battle_area:
      - slot: <current_attacker>
        damage: +<return_dmg>    # 阻擋者的反擊（若有阻擋）
        hp: 0 / unit_id: null    # 若被破壞
  <non_active_player>:           # 防守方
    base:
      damage: +<attacker_ap>
      alive: false               # 若 damage ≥ hp
      status: null
    shields: -<N>                # 盾牌破壞或 Breach
    battle_area:
      - slot: <blocker_slot>
        damage: +<attacker_ap>
        hp: 0 / unit_id: null    # 若被破壞
  priority: <active_player>          # 戰鬥後優先權返回行動玩家
  game_over: true / winner: <active_player>  # CR-4.9 直擊
  battle_log:                    # 模板見 ui_templates.md §log_damage
    - "<attacker> deals <N> damage to <target>"
```
