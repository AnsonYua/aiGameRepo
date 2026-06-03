---
name: skill_termination
triggers: [concede]
phase_lock: any
---

# skill_termination

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

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
  battle_log:                          # 模板見 ui_templates.md §log_win
    - "<winner> wins by <reason>"
```
