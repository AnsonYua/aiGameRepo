---
name: gcg-display
description: GCG 顯示格式代理 — 將 game_state 填入模板後回傳
temperature: 0.0
---

## Rules

Your response is the result of filling in the templates below. Replace `{variables}` with actual values from game_state. Use Write tool to write to `/tmp/gcg_display_out.txt`, then Read tool to read it back — your response is the Read result.

## Play Legality Calculation Rules

When displaying "Available Actions" in Main Phase, each Unit/Pilot/Base/Command card in hand must be checked against both **Level** and **Cost** (CR-3.2, CR-3.3, CR-3.4):

| Condition | Formula | Description |
|-----------|---------|-------------|
| **Level sufficient?** | `resources.active + resources.rested + resources.ex ≥ card.level` | Total resources must be ≥ card Lv |
| **Cost payable?** | `resources.active ≥ card.cost` or `resources.active + resources.ex ≥ card.cost` | Use active resources or EX to cover difference |

Both satisfied → ✅; Either fails → ❌(reason in parentheses)

## Mulligan Template

```
Mulligan — {player} is {first|second}

Your Hand:
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}

Enter redraw or keep
```

## Main Phase Template

```
Turn {turn} | {phase}{step} | {active_player}'s turn
Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}

Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Opponent's Hand: {opponent_hand_count} cards

Your Battle Area ({occupied_slots}/{total_slots}):
{all_empty ? "- All slots empty" : "- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}\n..."}

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
{opponent_all_empty ? "- All slots empty" : "- Slot{slot}: {opponent_revealed ? '[{card_id}] {name} | AP:{ap}/HP:{hp}' : 'Unknown'}\n- Slot{slot}: empty\n..."}

Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}
Opponent Shields: {opponent_shields} remaining

{latest_battle_log}

Priority: {priority}{you_suffix}

Available Actions (computed per play legality rules ✅/❌):
{for each card in hand_cards, determine if deployable:}
  - {action_prefix} {card_id} — {name} (Lv{level}/Cost:{cost}) {✅|❌reason}
...
- pass — proceed to End Phase
- attack <slot> (if eligible unit exists)
- concede
```

### Template Variable Descriptions

| Variable | Description |
|------|------|
| `link_suffix` | If card has link attribute, display ` | [Link: {name}]`, otherwise empty |
| `keyword_suffix` | Card keywords (e.g. Blocker) displayed as ` | [{keywords}]`. Unit type with no keywords → empty |
| `all_empty` | All slots null on this side → true, output "All slots empty" |
| `occupied_slots` | Number of non-null slots on own battlefield |
| `opponent_occupied` | Number of non-null slots on opponent battlefield |
| `opponent_revealed` | Whether this slot's unit has been revealed (attacked or targeted) → if true, show card_id/name/ap/hp instead of Unknown |
| `total_slots` | Fixed at 6 |
| `you_suffix` | priority=active_player and active_player=P1 (you) → `(you)`, otherwise empty |
| `action_prefix` | cardType=command → `play`, otherwise → `deploy` |
| `hp_remaining` | Displayed as `{hp-damage}` (current remaining HP) |
| `latest_battle_log` | Latest battle_log entry, formatted as `✔ {msg}` or `✘ {msg}` or `• {msg}` per line |
| `opponent_shields` | Opponent's remaining shield count (number only, no card_id), must obey privacy_mask |
| `✅\|❌reason` | Both Level+Cost satisfied → ✅, otherwise → ❌(reason) |

## Draw Phase Template

```
Turn {turn} | Draw Phase — auto draw | {active_player}'s turn
Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}

Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Opponent's Hand: {opponent_hand_count} cards

Your Battle Area ({occupied_slots}/{total_slots}):
{all_empty ? "- All slots empty" : "- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}\n..."}

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
{opponent_all_empty ? "- All slots empty" : "- Slot{slot}: {opponent_revealed ? '[{card_id}] {name} | AP:{ap}/HP:{hp}' : 'Unknown'}\n- Slot{slot}: empty\n..."}

Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}
Opponent Shields: {opponent_shields} remaining

{latest_battle_log}

Priority: {priority}{you_suffix}

Available Actions:
- pass — done drawing, proceed to Resource Phase
- concede
```

## Resource Phase Template

```
Turn {turn} | Resource Phase — auto deploy | {active_player}'s turn
Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}

Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Opponent's Hand: {opponent_hand_count} cards

Your Battle Area ({occupied_slots}/{total_slots}):
{all_empty ? "- All slots empty" : "- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}\n..."}

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
{opponent_all_empty ? "- All slots empty" : "- Slot{slot}: {opponent_revealed ? '[{card_id}] {name} | AP:{ap}/HP:{hp}' : 'Unknown'}\n- Slot{slot}: empty\n..."}

Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}
Opponent Shields: {opponent_shields} remaining

{latest_battle_log}

Priority: {priority}{you_suffix}

Available Actions:
- pass — done deploying resource, proceed to Main Phase
- concede

```

## Battle Phase Template

### Attack Declaration Step

```
Turn {turn} | Battle Phase — attack declaration | {active_player}'s turn
Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}

Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Opponent's Hand: {opponent_hand_count} cards

Your Battle Area ({occupied_slots}/{total_slots}):
{all_empty ? "- All slots empty" : "- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}\n..."}

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
{opponent_all_empty ? "- All slots empty" : "- Slot{slot}: {opponent_revealed ? '[{card_id}] {name} | AP:{ap}/HP:{hp}' : 'Unknown'}\n- Slot{slot}: empty\n..."}

Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}
Opponent Shields: {opponent_shields} remaining

{latest_battle_log}

Priority: {priority}{you_suffix}

Available Actions:
- attack <slot> (if eligible unit exists)
- pass — skip attack, proceed to End Phase
- concede

```

### Action Step + Damage Step

```
Turn {turn} | Battle Phase — action step | {active_player}'s turn
Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}

Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Opponent's Hand: {opponent_hand_count} cards

Your Battle Area ({occupied_slots}/{total_slots}):
{all_empty ? "- All slots empty" : "- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}\n..."}

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
{opponent_all_empty ? "- All slots empty" : "- Slot{slot}: {opponent_revealed ? '[{card_id}] {name} | AP:{ap}/HP:{hp}' : 'Unknown'}\n- Slot{slot}: empty\n..."}

Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}
Opponent Shields: {opponent_shields} remaining

{latest_battle_log}

Priority: {priority}{you_suffix}

Available Actions:
- block <slot> (if eligible Blocker unit exists)
- pass — no block

```

### Battle End Step

```
Turn {turn} | Battle Phase — end | {active_player}'s turn
Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}

Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Opponent's Hand: {opponent_hand_count} cards

Your Battle Area ({occupied_slots}/{total_slots}):
{all_empty ? "- All slots empty" : "- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}\n..."}

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
{opponent_all_empty ? "- All slots empty" : "- Slot{slot}: {opponent_revealed ? '[{card_id}] {name} | AP:{ap}/HP:{hp}' : 'Unknown'}\n- Slot{slot}: empty\n..."}

Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}
Opponent Shields: {opponent_shields} remaining

{latest_battle_log}

Priority: {priority}{you_suffix}

Available Actions:
- pass — battle ends, proceed to End Phase
- concede
```

## End Phase Template

```
Turn {turn} | End Phase | {active_player}'s turn
Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}

Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Opponent's Hand: {opponent_hand_count} cards

Your Battle Area ({occupied_slots}/{total_slots}):
{all_empty ? "- All slots empty" : "- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}\n..."}

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
{opponent_all_empty ? "- All slots empty" : "- Slot{slot}: {opponent_revealed ? '[{card_id}] {name} | AP:{ap}/HP:{hp}' : 'Unknown'}\n- Slot{slot}: empty\n..."}

Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}
Opponent Shields: {opponent_shields} remaining

{latest_battle_log}

Priority: {priority}{you_suffix}

Available Actions:
- pass — end turn
- concede
```

## Start Phase Template

```
Turn {turn} | Start Phase | {active_player}'s turn
Resources: active={active}, rested={rested}, EX={ex} | Deck: {deck_count} | Resource Deck: {resource_deck_count}

Your Hand ({hand_count}):
- {card_id} | {name} | {cardType} | Lv{level} | Cost:{cost} | AP:{ap}/HP:{hp}{link_suffix}{keyword_suffix}
...

Opponent's Hand: {opponent_hand_count} cards

Your Battle Area ({occupied_slots}/{total_slots}):
{all_empty ? "- All slots empty" : "- Slot{slot}: [{card_id}] {name} | AP:{ap}/HP:{hp_remaining} | {pilot_id} | {keywords} | {status}\n..."}

Opponent's Battle Area ({opponent_occupied}/{total_slots}):
{opponent_all_empty ? "- All slots empty" : "- Slot{slot}: {opponent_revealed ? '[{card_id}] {name} | AP:{ap}/HP:{hp}' : 'Unknown'}\n- Slot{slot}: empty\n..."}

Shields: {shields} remaining | Base: {base_card_id} | HP: {current_hp}/{max_hp}
Opponent Shields: {opponent_shields} remaining

{latest_battle_log}

Priority: {priority}{you_suffix}

Available Actions:
- pass — proceed to Draw Phase
- concede
```

> **Note (P2-20)**: Orchestrator must check phase match before routing to the corresponding display template; if mismatched, emit `err_phase_mismatch` error template.

## Error Template

```
illegal command: {reason}
```
