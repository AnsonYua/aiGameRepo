---
name: skill_activate
triggers: [activate]
phase_lock: main, battle(action), end(action)
---

# skill_activate — 啟動效果

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

啟動卡片的主動效果（CR-10.3：[Activate/Main] 或 [Main]/[Action]）。通常用於 Base 卡或 Unit 能力。

## 輸入

- `game_state.md` — 當前狀態
- `card_data[card_id]` — 預先提取的卡片資料（來自 orchestrator）
- `effect_id` — 要啟動哪個效果（來自卡片的 interpreted effects）

## 流程

1. **找到效果**：比對 `effect_id` 與卡片的 interpreted `effects[]`
2. **檢查啟動時機**：必須符合當前階段/子步驟（CR-10.3）
3. **支付費用**：
   - `resource(N)`：橫置 N 個直立資源
   - `rest_self`：橫置來源卡（戰區欄位或 base.status→rested）
   - `resource(N)+once`：支付 + 檢查 `active_effects[].used_this_turn`（CR-10.4）
4. **應用效果**（依動作類型）：
   - `deploy_token`：將代幣加入第一個空戰區欄位
   - `ap_boost(N)`：透過 active_effects 暫時套用到目標
   - `shield_to_hand(N)`：將盾牌移至手牌。shields: -N 表示數量；實際 card_id 由 orchestrator 透過 state_diff 追蹤
   - `rest_target`：橫置敵方單位
   - 等等
5. **記錄 oncePerTurn**：若有，設定 `active_effects[].used_this_turn=true`

## 輸出

```yaml
state_diff:
  <active_player>:
    resources:
      active: -<cost>
      rested: +<cost>
    shields: -<N>               # 若為 shield_to_hand
    base:
      status: rested             # 若 rest_self 在 base 上
    active_effects:
      - add:
          effectId: <effectId>
          source: <card_id>
          timing: UNTIL_END_OF_TURN|ONCE_PER_TURN
          parameters: {<key>: <value>}
          used_this_turn: true   # 若 oncePerTurn
    battle_area:                 # 合併變更（rest_target + deploy_token 等）
      - slot: <N>
        unit_id: <token_id|null>   # null=不變, token_id=部署
        pilot_id: null
        ap: <from token data|unchanged>
        hp: <from token data|unchanged>
        damage: 0
        status: rested|null        # rested=rest_target, null=不變
        keywords: []
        link: false
  battle_log:                          # 模板見 ui_templates.md §log_activate
    - "<active_player> activates <effect_id> on <card_id>"
```
