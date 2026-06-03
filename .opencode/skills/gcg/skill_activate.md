---
name: skill_activate
triggers: [activate]
phase_lock: main, battle(action), end(action)
---

# skill_activate

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

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
   - `shield_to_hand(N)`: move shield to hand。從 `.deck_tracking.json` 該玩家的 `shields_cards` 移除最外層（最後一張），加入手牌（由 orchestrator 更新）
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
    base:
      status: rested             # if rest_self on base
    active_effects:
      - add:
          effectId: <effectId>
          source: <card_id>
          timing: UNTIL_END_OF_TURN|ONCE_PER_TURN
          parameters: {<key>: <value>}
          used_this_turn: true   # if oncePerTurn
    battle_area:                 # merged changes (rest_target + deploy_token etc.)
      - slot: <N>
        unit_id: <token_id|null>   # null=unchanged, token_id=deploy
        pilot_id: null
        ap: <from token data|unchanged>
        hp: <from token data|unchanged>
        damage: 0
        status: rested|null        # rested=rest_target, null=unchanged
        keywords: []
        link: false
  battle_log:                          # 模板見 ui_templates.md §log_activate
    - "<active_player> activates <effect_id> on <card_id>"
```
