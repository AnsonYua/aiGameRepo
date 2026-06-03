---
name: skill_damage
phase_lock: battle
note: not a standalone route — loaded alongside skill_pass.md when phase=battle
---

# skill_damage

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

Damage resolution reference (CR-5.2, CR-5.3). Orchestrator loads this alongside `skill_pass.md` when phase=battle. Not a standalone route.

## Flow

1. Read `current_attacker` slot, look up attacker in `active_player.battle_area`
2. Check if blocked: `non_active_player.battle_area` has any slot with `status=rested` after block was declared
3. **If blocked**: attacker deals AP damage to blocker, blocker deals its AP damage to attacker. Apply simultaneously unless First Strike (CR-5.7): FS deals first; if target destroyed, no return damage
4. **If not blocked**: damage goes to defense layer per CR-4.3:
   - shields>0 + base alive → damage to base (base.damage += attacker AP, CR-4.4)
   - shields>0 + base dead → damage to top shield (shield destroyed, check Burst CR-6.5)
   - shields=0 → direct hit → game loss for non-active player (CR-4.9)
5. **Breach (CR-6.3)**: extra damage = attacker's Breach value, applies to shield area (target per CR-4.3). Breach activates regardless of blocker/trade outcome (FAQ Q55). Shield area empty → Breach does nothing (FAQ Q54)
6. **0 AP attacker**: cannot destroy any defense layer (CR-4.8), still Breach applies if any
7. **Check destruction**: unit/base with damage ≥ HP is destroyed (removed from battle_area to trash, or base.alive=false). Token → removal (CR-6.7)
8. **Burst (CR-6.5)**: if a Burst card is among destroyed shields, the owning player may choose to trigger it. Record in `active_effects` for resolution. 實際被破壞的盾牌卡 ID 記錄於 `.deck_tracking.json`（由 orchestrator 在 §10 更新）
- Then: step → battle_end. If no pending burst → clear current_attacker → return to main (CR-5.3)

## Output

```yaml
state_diff:
  step: battle_end / null        # null if no burst → return to main
  current_attacker: null         # cleared
  <active_player>:               # attacker side
    battle_area:
      - slot: <current_attacker>
        damage: +<return_dmg>    # blocker's counter (if blocked)
        hp: 0 / unit_id: null    # if destroyed
  <non_active_player>:           # defender side
    base:
      damage: +<attacker_ap>
      alive: false               # if damage ≥ hp
      status: null
    shields: -<N>                # shield destroyed or Breach
    battle_area:
      - slot: <blocker_slot>
        damage: +<attacker_ap>
        hp: 0 / unit_id: null    # if destroyed
  priority: <active_player>          # return priority to active_player after battle
  game_over: true / winner: <active_player>  # CR-4.9 direct hit
  battle_log:                    # 模板見 ui_templates.md §log_damage
    - "<attacker> deals <N> damage to <target>"
```
