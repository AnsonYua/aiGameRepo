---
name: skill_draw
triggers: [draw]
phase_lock: draw
---

# skill_draw

Draw phase (CR-2.5). Active player draws 1 card from deck.

## Flow

1. Deck count > 0 → draw 1 card (deck_count -= 1, hand gains 1 card)
2. Deck count = 0 → immediate loss (CR-8.2)

## Output

```yaml
state_diff:
  <active_player>:
    hand_cards:
      - add: <card_id>
    deck_count: -1
  battle_log:
    - "<active_player> draws a card"
```
