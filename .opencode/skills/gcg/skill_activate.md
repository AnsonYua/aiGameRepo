---
name: skill_activate
triggers: [activate]
phase_lock: main, end(action)
---

# skill_activate

Activate a card's activated ability (CR-10.3: [Activate/Main] or [Main]/[Action]). Typically used on Base cards or Unit abilities.

## Input

- `game_state.md` — current state
- `card_data[card_id]` — pre-fetched card data (from orchestrator)
- `effect_id` — which ability to activate (from card's interpreted effects)

## Flow

1. **Find the effect**: Match `effect_id` against the card's interpreted `effects[]`
2. **Check activation window**: Must match current phase/step (CR-10.3)
3. **Pay cost**:
   - `resource(N)`: rest N active resources
   - `rest_self`: rest the source card (battle_area slot or base.status→rested)
   - `resource(N)+once`: pay + check `active_effects[].used_this_turn` (CR-10.4)
4. **Apply effect** (varies by action type):
   - `deploy_token`: add token to first empty battle_area slot
   - `ap_boost(N)`: apply temporarily to target via active_effects
   - `shield_to_hand(N)`: move shield to hand
   - `rest_target`: rest enemy unit
   - etc.
5. **Record oncePerTurn**: If applicable, set `active_effects[].used_this_turn=true`

## Output

```yaml
state_diff:
  <active_player>:
    resources:
      active: -<cost>
      rested: +<cost>
    shields: -<N>               # if shield_to_hand
    battle_area:                 # if targets units
      - slot: <N>
        status: rested           # if rest_target
    base:
      status: rested             # if rest_self on base
    active_effects:
      - add:
          effectId: <effectId>
          source: <card_id>
          timing: UNTIL_END_OF_TURN|ONCE_PER_TURN
          parameters: {<key>: <value>}
          used_this_turn: true   # if oncePerTurn
    battle_area:                 # if deploy_token
      - slot: <N>
        unit_id: <token_id>
        ap: <from token data>
        hp: <from token data>
        damage: 0
        status: null
        keywords: []
        link: false
  battle_log:
    - "<active_player> activates <effect_id> on <card_id>"
```
