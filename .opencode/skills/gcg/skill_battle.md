---
name: skill_battle
triggers: [attack]
phase_lock: main
---

# skill_battle

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
  <active_player>:
    battle_area:
      - slot: <attacking_slot>
        status: rested         # attacker becomes rested after declaration
  battle_log:
    - "<active_player> attacks with slot <N>"
```
