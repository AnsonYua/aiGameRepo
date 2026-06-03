---
name: skill_play_card
triggers: [play, deploy, pair]
phase_lock: main, battle(action), end(action)
---

# skill_play_card

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

Play card from hand to appropriate zone. Handles all card types: Unit, Pilot, Command, Base, dual-purpose [Pilot], and pairing.

## Input

- `game_state.md` — current game state
- `card_data[card_id]` — pre-fetched card stats + interpreted effects (from orchestrator)

## Flow

### 1. Pay Cost (CR-3.2, CR-3.3)

- `Level = resources.active + resources.rested + resources.ex` must be ≥ `card_data[card_id].level`
- Pay cost: rest `card_data[card_id].cost` active resources (active -= cost, rested += cost)
- If insufficient active resources, EX can be consumed to cover difference (CR-3.4)

### 2. Dispatch by cardType

**Unit** (`deploy <card_id>`):
- Place in first empty battle_area slot (slot 0-5, first where unit_id=null)
- Set ap=card_data[].ap, hp=card_data[].hp, damage=0, status=null, keywords=[], link=false
- If all 6 slots occupied → must trash an existing unit to free a slot (CR-5.11)
- Token type (level=0) cannot be played from hand（見 ui_templates.md §err_token_play）

**Pilot** (`deploy <card_id>`):
- Place in first empty battle_area slot
- Set ap=card_data[].ap, hp=card_data[].hp, damage=0, status=null, keywords=[], link=false

**Command** (`play <card_id>`):
- Card effect resolves immediately based on interpreted effects
- Card goes to trash after resolution
- Activation window must match current phase/step (CR-10.3)

**Base** (`deploy <card_id>`):
- Old Base (current `base`) goes to trash (CR-7.3)
- Top shield card moves to hand (CR-7.3)。從 `.deck_tracking.json` 該玩家的 `shields_cards` 移除最外層（最後一張），加入手牌（由 orchestrator 更新）
- New Base card replaces it: card_id, hp=card_data[].hp, ap=card_data[].ap, damage=0, alive=true, status=active
- [Deploy] trigger resolves (CR-6.6)

**Dual-purpose [Pilot]** (choose mode):
- `play` → treat as Command: resolve effect, go to trash
- `deploy` → treat as Pilot: place in battle_area with the [Pilot] stats

### 3. Pair (`pair <pilot_card_id> <slot>`)

- Target slot must have unit_id != null and pilot_id = null
- Pilot card must be in hand (or just deployed)
- Set pilot_id in the slot
- Pilot card removed from hand
- If pilot can link (pilot name in card_data[unit_id].link) → set link=true (CR-6.4)
- [When Paired] triggers resolve (from interpreted effects with trigger=on_pair)

## Output

```yaml
state_diff:
  <active_player>:
    resources:
      active: -<cost>     # after paying cost
      rested: +<cost>
      ex: -<ex_used>
    hand_cards:
      - remove: <card_id>
    battle_area:           # for deploy/pair
      - slot: <N>
        unit_id: "<card_id or unchanged>"
        pilot_id: "<pilot_id or unchanged>"
        ap: <from card_data or unchanged>
        hp: <from card_data or unchanged>
        damage: 0
        status: null
        keywords: []
        link: <true|false>
    base:                  # for base deploy
      card_id: "<new card_id>"
      ap: <new ap>
      hp: <new hp>
      damage: 0
      alive: true
      status: active
    shields: -1            # if base deploy (top shield → hand)
    trash:
      - add: <old card_id>
  battle_log:                          # 模板見 ui_templates.md §log_play_card
    - "<active_player> plays/deploys/pairs <card_id>"
```
