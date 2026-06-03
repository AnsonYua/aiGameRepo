---
name: skill_block
triggers: [block]
phase_lock: battle
---

# skill_block

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

Declare a blocker (CR-5.8, CR-6.1). Non-active player intercepts an attack.

## Input

- `game_state.md` — current state
- `slot` — which battle_area slot is blocking

## Flow

1. **Phase/step check**: phase must be battle, step must be attack
2. **Read current_attacker**: the slot in `game_state.current_attacker` is being blocked
3. **Check blocker eligibility**:
   - Unit must have Blocker keyword (CR-6.1)
   - Unit must be not rested (status != rested)
   - Unit must belong to the non-active player
4. **Execute block**: rest the blocker (CR-5.8)
5. **Redirect**: attack now targets the blocker instead of defense layer (CR-5.9)
6. **Advance step**: step → action (priority window opens, CR-5.12)

## Output

```yaml
state_diff:
  step: action                  # advance to action step for priority (CR-5.12)
  <non_active_player>:
    battle_area:
      - slot: <blocking_slot>
        status: rested          # blocker becomes rested
  battle_log:                          # 模板見 ui_templates.md §log_block
    - "<non_active_player> blocks with slot <N>"
```
