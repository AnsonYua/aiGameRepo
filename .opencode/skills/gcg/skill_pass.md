---
name: skill_pass
triggers: [pass, end turn]
phase_lock: any
---

# skill_pass

Pass priority (CR-2.10). Advances the game through phases/steps when both players pass.

## Flow by current phase

### main + pass
- Phase → end, step → action
- Non-active player gets priority first (CR-2.9)

### main + end turn
- Alias for `pass` (same behavior)

### battle(action) + pass
- Both passed → advance to damage step
- Then: damage → battle_end → return to main (CR-5.3)

### end(action) + pass
- Both passed → advance to cleanup
- Cleanup: discard if hand ≥11 (CR-8.1), then end turn
- active_player switches, phase → start

### any other phase + pass
- No effect (phase continues normally)

## Output

```yaml
state_diff:
  phase: <next_phase>           # end / battle / main / start
  step: <next_step|null>        # action / damage / battle_end / cleanup / null
  <active_player>:              # if end turn cleanup
    hand_cards:
      - remove: [<discarded_ids>]   # if hand ≥11, discard to 10
  active_player: <switched>     # if end phase cleanup completed
  battle_log:
    - "<active_player> passes / ends turn"
```
