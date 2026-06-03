---
name: skill_redraw
triggers: [redraw, mulligan]
phase_lock: pre-game
---

# skill_redraw

Mulligan / redraw (CR-1.8). P1 decides first, each player may redraw once.

## Input

- `game_state.md` — current pre-game state (5 cards in hand)
- `player_id` — who called redraw

## Flow

1. P1 chooses first: redraw or keep
2. P2 chooses second: redraw or keep
3. If redraw: return hand to bottom of deck, draw 5 new cards, shuffle
4. Both players can only redraw once

## Output

```yaml
state_diff:
  p1:
    hand_cards: [<5 new card_ids>]
    deck_count: <unchanged (returned + redrawn)>
  p2:
    hand_cards: [<5 new card_ids>]
    deck_count: <unchanged>
  battle_log:
    - "P1 redraws"  # (if applicable)
    - "P2 keeps"    # (if applicable)
```
