---
name: skill_card_db
type: utility
note: card data interpretation reference — not a routable skill; loaded by orchestrator for card data pre-fetch
---

# skill_card_db — Card Data & Effect Interpretation

Central card database + effect interpretation skill. Reads raw `card/data/*.json`, interprets effects into a standardized format. All agents (AI Player, Orchestrator, Judge) consume the same interpreted format.

---

## Data Sources

| Source | Path | Content |
|--------|------|---------|
| Card details (raw) | `card/data/{set}Card.json` | Per-set catalog with raw JSON effects |
| Deck manifest | `card/gcgdecks.json` | Deck definitions + player→deck mapping |

---

## Card ID Format

Canonical: `{set_prefix}/{card_number}`

Example: `st01/ST01-001` → prefix=`st01`, file=`card/data/st01Card.json`, key=`ST01-001`

| Prefix | File |
|--------|------|
| `st01`–`st09` | `st{nn}Card.json` |
| `gd01`–`gd03` | `gd{nn}Card.json` |

Rule: `{prefix}` → `{prefix}Card.json`. No `/` in card_id → search all files.

---

## Effect Vocabulary (Shared Across All Agents)

Every raw effect rule from `card/data/*.json` is interpreted into this standardized structure:

```yaml
- effectId: <string>         # original effectId from card data
  trigger: <trigger_type>    # when this effect activates
  cost: <cost_type>          # what you pay (if any)
  action: <action_type>      # what it does
  target: <target_scope>     # who it affects
  value: <int>               # numeric parameter (if applicable)
  duration: <duration_type>  # how long it lasts
  condition: <string|null>   # condition string (e.g., "paired")
  oncePerTurn: <bool>        # true if [Once per Turn]
  summary: <string>          # human-readable one-liner
```

### Trigger Types

| Raw `timing.eventTrigger` / `type` | Standardized `trigger` | Meaning |
|---|---|---|
| `PAIRING_COMPLETE` | `on_pair` | Triggers when Unit + Pilot pair |
| `ENTERS_PLAY` | `on_deploy` | Triggers when card enters play |
| `END_OF_TURN` | `end_of_turn` | Triggers at end of your turn |
| `ATTACK_PHASE` | `on_attack` | Triggers when unit attacks |
| `BURST_CONDITION` | `on_burst` | Triggers when shield breaks |
| `ATTACK_REDIRECT` | `on_block` | Blocker redirects attack |
| `type: play` | `on_play` | Manual: play card from hand |
| `type: activated` | `manual_activate` | Manual: activate ability with cost |
| `type: continuous` | `continuous` | Always active while condition met |
| `type: special` | `special` | Special subtype (pilot_designation etc.) |

### Cost Types

| Raw `cost` field | Standardized `cost` | Meaning |
|---|---|---|
| absent / none | `none` | Free, no cost |
| `{ resource: N }` | `resource(N)` | Rest N active resources |
| `{ resource: N, oncePerTurn: true }` | `resource(N)+once` | Rest N resources, once per turn |
| `{ rest: self }` | `rest_self` | Rest this card (Base status→rested) |
| `{ cost: rest_self }` (in params) | `rest_self` | Blocker: rest self to redirect |

### Action Types

| Raw `action` | Standardized `action` | Meaning |
|---|---|---|
| `heal` | `heal(N)` | Recover N HP |
| `damage` | `damage(N)` | Deal N damage |
| `draw` | `draw(N)` | Draw N cards |
| `modifyAP` (value>0) | `ap_boost(N)` | Gain N AP |
| `modifyAP` (value<0) | `ap_reduce(N)` | Lose N AP |
| `rest` | `rest_target` | Rest enemy/any unit |
| `setActive` | `activate_resource` | Set a resource to active |
| `redirect_attack` | `block` | Redirect attack to self |
| `restrict_attack` | `no_player_attack` | Can't attack player |
| `addToHand` (from shield) | `shield_to_hand(N)` | Retrieve shield to hand |
| `addToHand` (from self) | `return_to_hand` | Return self to hand |
| `deploy` (self) | `deploy_self` | Deploy self (burst) |
| `conditionalTokenDeploy` | `deploy_token(N)` | Deploy N token units |
| `activate_ability` | `activate_ability` | Activate the card's Main effect |
| `designate_pilot` | `pilot_dual` | Dual-purpose [Pilot] on Command |

### Target Scopes

| Raw `target.scope` + `target.type` | Standardized `target` | Meaning |
|---|---|---|
| `{type: unit, scope: source}` | `self` | The card itself |
| `{type: unit, scope: self}` | `self_unit(1)` | 1 friendly unit |
| `{type: unit, scope: self_all_unit}` | `self_all_units` | All friendly units |
| `{type: unit, scope: opponent}` | `opponent_unit(1)` | 1 enemy unit |
| `{type: energy, scope: self_resource}` | `self_resource(1)` | 1 own resource |
| `{type: card, scope: self_shield}` | `self_shield(1)` | 1 shield card |
| `{type: card, scope: self}` | `self_hand` | Own hand |
| `{type: unit, scope: self, filters: {linkStatus: linked}}` | `self_linked_units` | All linked units |

### Duration Types

| Raw `timing.duration` | Standardized `duration` |
|---|---|
| `instant` (or absent) | `instant` |
| `UNTIL_END_OF_TURN` | `until_end_of_turn` |
| `continuous` | `continuous` |
| `YOUR_TURN` | `your_turn` |

---

## Effect Interpretation Rules

For each `effectId` pattern, apply these interpretation rules:

### Deploy Triggers (`on_deploy`)

| effectId | Standard Output |
|---|---|
| `deploy_rest_low_hp` | `trigger: on_deploy, cost: none, action: rest_target, target: opponent_unit(1)(HP≤2), duration: instant` |
| `deploy_shield_to_hand` | `trigger: on_deploy, cost: none, action: shield_to_hand(1), target: self_shield, duration: instant` |

### Pair Triggers (`on_pair`)

| effectId | Standard Output |
|---|---|
| `paired_white_base_draw` | `trigger: on_pair, cost: none, action: draw(1), target: self, duration: instant, condition: pilot_trait=White Base Team` |
| `pair_ap_boost_all` | `trigger: continuous, cost: none, action: ap_boost(1), target: self_all_units, duration: your_turn, condition: paired` |
| `paired_ap_reduction` | `trigger: on_pair, cost: none, action: ap_reduce(3), target: opponent_unit(1)(Lv≤5), duration: until_end_of_turn` |
| `paired_rest_medium_hp` | `trigger: on_pair, cost: none, action: rest_target, target: opponent_unit(1)(HP≤5), duration: instant` |

### Turn-End Triggers (`end_of_turn`)

| effectId | Standard Output |
|---|---|
| `repair_2` | `trigger: end_of_turn, cost: none, action: heal(2), target: self, duration: instant` |

### Attack Triggers (`on_attack`)

| effectId | Standard Output |
|---|---|
| `attack_activate_resource` | `trigger: on_attack, cost: none, action: activate_resource, target: self_resource(1), duration: instant, oncePerTurn: true, condition: paired` |

### Burst Triggers (`on_burst`)

| effectId | Standard Output |
|---|---|
| `burst_add_to_hand` | `trigger: on_burst, cost: none, action: return_to_hand, target: self_hand, duration: instant` |
| `burst_activate_main` | `trigger: on_burst, cost: none, action: activate_ability, target: self, duration: instant` |
| `burst_deploy` | `trigger: on_burst, cost: none, action: deploy_self, target: self, duration: instant` |

### Main Phase Play (`on_play`)

| effectId | Standard Output |
|---|---|
| `main_damage_rested` | `trigger: on_play, cost: resource(1), action: damage(1), target: opponent_unit(1)(rested), duration: instant` |
| `main_heal_friendly` | `trigger: on_play, cost: resource(1), action: heal(3), target: self_unit(1), duration: instant` |
| `main_action_ap_reduction` | `trigger: on_play, cost: resource(1), action: ap_reduce(3), target: opponent_unit(1), duration: until_end_of_turn` — usable in MAIN_PHASE or ACTION_STEP |

### Activated Abilities (`manual_activate`)

| effectId | Standard Output |
|---|---|
| `activate_conditional_token_deploy` | `trigger: manual_activate, cost: resource(2), action: deploy_token, target: self_battle_area, duration: instant, oncePerTurn: true` — chooses T-001/T-002/T-003 based on units in play |
| `activate_boost_link_units` | `trigger: manual_activate, cost: rest_self, action: ap_boost(1), target: self_linked_units, duration: until_end_of_turn` |

### Continuous / Restrictions

| effectId | Standard Output |
|---|---|
| `blocker` | `trigger: on_block, cost: rest_self, action: block, target: self, duration: instant` |
| `attack_restriction` | `trigger: continuous, cost: none, action: no_player_attack, target: self, duration: continuous` |

### Special

| effectId | Standard Output |
|---|---|
| `pilot_designation` | `trigger: special, cost: none, action: pilot_dual, target: self, duration: continuous, parameters: {pilotName, AP, HP}` |

---

## card_data Output Format (Orchestrator Pre-fetch)

When the orchestrator pre-fetches card data for the AI player (or any agent), it produces this structure for each card_id in hand:

```yaml
card_data:
  <card_id>:
    # --- Stats (always) ---
    level: <int>
    cost: <int>
    cardType: unit|pilot|command|base
    ap: <int>
    hp: <int>
    link: [<string>]       # pilot names for pairing

    # --- Interpreted Effects (always) ---
    effects:
      - trigger: <trigger_type>
        cost: <cost_type>
        action: <action_type>
        target: <target_scope>
        value: <int>
        duration: <duration_type>
        condition: <string|null>
        oncePerTurn: <bool>
        summary: <string>

```

### Examples

```yaml
st01/ST01-001:                         # Gundam
  level: 4
  cost: 3
  cardType: unit
  ap: 3
  hp: 4
  link: ["Amuro Ray"]
  effects:
    - trigger: end_of_turn
      cost: none
      action: heal(2)
      target: self
      duration: instant
      condition: null
      oncePerTurn: false
      summary: "End of turn → heal 2 HP on self"
    - trigger: continuous
      cost: none
      action: ap_boost(1)
      target: self_all_units
      duration: your_turn
      condition: paired
      oncePerTurn: false
      summary: "While paired → your Units get AP+1 during your turn"

st01/ST01-015:                         # White Base
  level: 3
  cost: 2
  cardType: base
  ap: 0
  hp: 5
  link: []
  effects:
    - trigger: on_burst
      cost: none
      action: deploy_self
      target: self
      duration: instant
      summary: "Burst → deploy this card"
    - trigger: on_deploy
      cost: none
      action: shield_to_hand(1)
      target: self_shield
      duration: instant
      summary: "Deploy → add 1 shield to hand"
    - trigger: manual_activate
      cost: resource(2)
      action: deploy_token
      target: self_battle_area
      duration: instant
      oncePerTurn: true
      summary: "Activate [Once/Turn] (2) → deploy T-001/T-002/T-003 token based on units in play"

st01/ST01-012:                         # Thoroughly Damaged
  level: 2
  cost: 1
  cardType: command
  ap: 0
  hp: 1
  link: []
  effects:
    - trigger: on_play
      cost: resource(1)
      action: damage(1)
      target: opponent_unit(1)(rested)
      duration: instant
      summary: "Main → deal 1 damage to rested enemy unit"
    - trigger: special
      cost: none
      action: pilot_dual
      target: self
      duration: continuous
      summary: "[Pilot] can be deployed as Hayato Kobayashi (AP 0, HP 1)"
```

---

## Lookup Procedures

### 1. `get_card(card_id)` — Full raw card data

Same as before: parse card_id → read JSON file → return raw card object.

### 2. `interpret_effects(card_id)` — Standardized effect interpretations

1. `get_card(card_id)` → raw card
2. For each rule in the card's `effects.rules[]`, apply Effect Interpretation Rules (above) — this is an internal step, raw JSON never leaves this skill
3. Return array of standardized effect objects

### 3. `build_card_data(card_ids[])` — Pre-fetch bundle

1. For each card_id, call `get_card` then `interpret_effects`
2. Assemble into `card_data` YAML (as defined above)
3. Return the complete `card_data` object

### 4. `get_deck(playerId)` — Player's deck card list

Same as before: navigate `gcgdecks.json`.

### 5. `validate_card_stats(card_id, ap, hp)` — Judge validation

1. `get_card(card_id)` → check base ap/hp match
2. If unit type: deployed ap/hp must equal card base ap/hp (modifications tracked separately)

---

## Notes

- EX-BASE is a built-in card (ap=0, hp=3) not in any data file
- T cards require set prefix (e.g., `T-006` exists in both `st03` and `gd01`)
- Card data files are read-only; never modified at runtime
- All agents use `build_card_data(card_ids[])` — only stats + interpreted effects are exposed
- The raw `effects.rules[]` in `card/data/*.json` is authoring data, never passed to any agent
- New card sets may introduce new effectIds — add their interpretation rules when discovered
