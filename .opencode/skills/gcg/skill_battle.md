---
name: skill_battle
triggers: [attack]
phase_lock: main
---

# skill_battle

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

Declare an attack (CR-5). Transitions phase from main → battle(attack).

## Input

- `game_state.md` — current state
- `slot` — which battle_area slot is attacking

## Flow

1. **Check attack eligibility** (CR-5.4):
   - Unit must be not rested (status != rested)
   - Unit must have been deployed for 1+ full turn OR be a Link Unit (link=true)
2. **Check if unit can attack player** (from interpreted effects — some units restrict this)
3. **Switch phase/step**: phase=battle, step=attack
4. **Record attacker**: store which slot is the current attacker (for block/damage resolution)

## Output

```yaml
state_diff:
  phase: battle
  step: attack
  current_attacker: <slot>     # tracked for block/damage resolution
  <active_player>:
    battle_area:
      - slot: <attacking_slot>
        status: rested         # attacker becomes rested after declaration
  battle_log:                          # 模板見 ui_templates.md §log_attack
    - "<active_player> attacks with slot <N>"
```
