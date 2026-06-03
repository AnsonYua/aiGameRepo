---
name: skill_termination
triggers: [concede]
phase_lock: any
---

# skill_termination

Terminate the game (CR-9). Sets game_over=true and declares the winner.

## Trigger conditions

- `concede` command → immediate loss for the conceding player (CR-8.4)
- Loss detected by orchestrator (CR-4.9: shields=0 + direct hit, CR-8.2: deck=0 + need to draw)

## Flow

1. Determine loser:
   - conceding player → loser (CR-8.4)
   - player with shields=0 + direct damage → loser (CR-4.9)
   - player with deck=0 + need to draw → loser (CR-8.2)
2. Winner = the other player
3. Set game_over=true, winner, phase=null, step=null

## Output

```yaml
state_diff:
  phase: null
  step: null
  game_over: true
  winner: P1|P2
  battle_log:
    - "<winner> wins by <reason>"
```
