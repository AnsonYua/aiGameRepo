---
name: skill_block
triggers: [block]
phase_lock: battle
---

# skill_block

Declare a blocker (CR-5.8, CR-6.1). Non-active player intercepts an attack.

## Input

- `game_state.md` — current state
- `slot` — which battle_area slot is blocking

## Flow

1. **Phase/step check**: phase must be battle, step must be attack
2. **Check blocker eligibility**:
   - Unit must have Blocker keyword (CR-6.1)
   - Unit must be not rested (status != rested)
   - Unit must belong to the non-active player
3. **Execute block**: rest the blocker (CR-5.8)
4. **Redirect**: attack now targets the blocker instead of defense layer (CR-5.9)
5. **Advance step**: step → block (ready for action step)

## Output

```yaml
state_diff:
  step: block                   # advance to block step for action priority
  <non_active_player>:
    battle_area:
      - slot: <blocking_slot>
        status: rested          # blocker becomes rested
  battle_log:
    - "<non_active_player> blocks with slot <N>"
```
