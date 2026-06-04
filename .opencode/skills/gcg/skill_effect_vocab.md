---
name: skill_effect_vocab
type: reference
note: 標準化效果詞彙表與解譯規則 — 由 skill_card_db.md 參照；非獨立技能
---

# skill_effect_vocab — 效果詞彙表與解譯規則

由 `skill_card_db.md` 參照。定義所有標準化效果欄位的合法值與解譯規則。

---

## 觸發類型

| Raw `timing.eventTrigger` / `type` | 標準化 `trigger` | 說明 |
|---|---|---|
| `PAIRING_COMPLETE` | `on_pair` | Unit + Pilot 配對時觸發 |
| `ENTERS_PLAY` | `on_deploy` | 卡片進場時觸發 |
| `END_OF_TURN` | `end_of_turn` | 自己的回合結束時觸發 |
| `ATTACK_PHASE` | `on_attack` | 單位攻擊時觸發 |
| `BURST_CONDITION` | `on_burst` | 盾牌被破壞時觸發 |
| `ATTACK_REDIRECT` | `on_block` | Blocker 轉向攻擊 |
| `type: play` | `on_play` | 手動：從手牌打出 |
| `type: activated` | `manual_activate` | 手動：支付費用啟動效果 |
| `type: continuous` | `continuous` | 條件滿足時持續生效 |
| `type: special` | `special` | 特殊子類型（如 pilot_designation） |

## 費用類型

| Raw `cost` 欄位 | 標準化 `cost` | 說明 |
|---|---|---|
| absent / none | `none` | 免費，無需費用 |
| `{ resource: N }` | `resource(N)` | 橫置 N 個直立資源 |
| `{ resource: N, oncePerTurn: true }` | `resource(N)+once` | 橫置 N 個資源，每回合一次 |
| `{ rest: self }` | `rest_self` | 橫置此卡（Base status→rested） |
| `{ cost: rest_self }`（在 params 中） | `rest_self` | Blocker：橫置自身以轉向 |

## 動作類型

| Raw `action` | 標準化 `action` | 說明 |
|---|---|---|
| `heal` | `heal(N)` | 回復 N 點 HP |
| `damage` | `damage(N)` | 造成 N 點傷害 |
| `draw` | `draw(N)` | 抽 N 張牌 |
| `modifyAP` (value>0) | `ap_boost(N)` | 獲得 N 點 AP |
| `modifyAP` (value<0) | `ap_reduce(N)` | 失去 N 點 AP |
| `rest` | `rest_target` | 橫置敵方/任意單位 |
| `setActive` | `activate_resource` | 將資源設為直立 |
| `redirect_attack` | `block` | 將攻擊轉向自身 |
| `restrict_attack` | `no_player_attack` | 不可攻擊玩家 |
| `addToHand`（來自盾牌） | `shield_to_hand(N)` | 將盾牌收回手牌 |
| `addToHand`（來自自身） | `return_to_hand` | 將自身收回手牌 |
| `deploy`（自身） | `deploy_self` | 部署自身（burst） |
| `conditionalTokenDeploy` | `deploy_token(N)` | 部署 N 個代幣單位 |
| `activate_ability` | `activate_ability` | 啟動卡片的主要效果 |
| `designate_pilot` | `pilot_dual` | 雙用途 [Pilot] 指令卡 |

## 目標範圍

| Raw `target.scope` + `target.type` | 標準化 `target` | 說明 |
|---|---|---|
| `{type: unit, scope: source}` | `self` | 該卡本身 |
| `{type: unit, scope: self}` | `self_unit(1)` | 1 個己方單位 |
| `{type: unit, scope: self_all_unit}` | `self_all_units` | 所有己方單位 |
| `{type: unit, scope: opponent}` | `opponent_unit(1)` | 1 個敵方單位 |
| `{type: energy, scope: self_resource}` | `self_resource(1)` | 1 個己方資源 |
| `{type: card, scope: self_shield}` | `self_shield(1)` | 1 張盾牌卡 |
| `{type: card, scope: self}` | `self_hand` | 己方手牌 |
| `{type: unit, scope: self, filters: {linkStatus: linked}}` | `self_linked_units` | 所有共鳴單位 |

## 持續時間類型

| Raw `timing.duration` | 標準化 `duration` |
|---|---|
| `instant`（或無） | `instant` |
| `UNTIL_END_OF_TURN` | `until_end_of_turn` |
| `continuous` | `continuous` |
| `YOUR_TURN` | `your_turn` |

---

## 效果解譯規則

針對每個 `effectId` 模式，應用以下解譯規則：

### 出場觸發（`on_deploy`）

| effectId | 標準輸出 |
|---|---|
| `deploy_rest_low_hp` | `trigger: on_deploy, cost: none, action: rest_target, target: opponent_unit(1)(HP≤2), duration: instant` |
| `deploy_shield_to_hand` | `trigger: on_deploy, cost: none, action: shield_to_hand(1), target: self_shield, duration: instant` |

### 配對觸發（`on_pair`）

| effectId | 標準輸出 |
|---|---|
| `paired_white_base_draw` | `trigger: on_pair, cost: none, action: draw(1), target: self, duration: instant, condition: pilot_trait=White Base Team` |
| `pair_ap_boost_all` | `trigger: continuous, cost: none, action: ap_boost(1), target: self_all_units, duration: your_turn, condition: paired` |
| `paired_ap_reduction` | `trigger: on_pair, cost: none, action: ap_reduce(3), target: opponent_unit(1)(Lv≤5), duration: until_end_of_turn` |
| `paired_rest_medium_hp` | `trigger: on_pair, cost: none, action: rest_target, target: opponent_unit(1)(HP≤5), duration: instant` |

### 回合結束觸發（`end_of_turn`）

| effectId | 標準輸出 |
|---|---|
| `repair_2` | `trigger: end_of_turn, cost: none, action: heal(2), target: self, duration: instant` |

### 攻擊觸發（`on_attack`）

| effectId | 標準輸出 |
|---|---|
| `attack_activate_resource` | `trigger: on_attack, cost: none, action: activate_resource, target: self_resource(1), duration: instant, oncePerTurn: true, condition: paired` |

### 爆發觸發（`on_burst`）

| effectId | 標準輸出 |
|---|---|
| `burst_add_to_hand` | `trigger: on_burst, cost: none, action: return_to_hand, target: self_hand, duration: instant` |
| `burst_activate_main` | `trigger: on_burst, cost: none, action: activate_ability, target: self, duration: instant` |
| `burst_deploy` | `trigger: on_burst, cost: none, action: deploy_self, target: self, duration: instant` |

### 主要階段出牌（`on_play`）

| effectId | 標準輸出 |
|---|---|
| `main_damage_rested` | `trigger: on_play, cost: resource(1), action: damage(1), target: opponent_unit(1)(rested), duration: instant` |
| `main_heal_friendly` | `trigger: on_play, cost: resource(1), action: heal(3), target: self_unit(1), duration: instant` |
| `main_action_ap_reduction` | `trigger: on_play, cost: resource(1), action: ap_reduce(3), target: opponent_unit(1), duration: until_end_of_turn` — 可在 MAIN_PHASE 或 ACTION_STEP 使用 |

### 啟動效果（`manual_activate`）

| effectId | 標準輸出 |
|---|---|
| `activate_conditional_token_deploy` | `trigger: manual_activate, cost: resource(2), action: deploy_token, target: self_battle_area, duration: instant, oncePerTurn: true` — 依據場上單位選擇 T-001/T-002/T-003 |
| `activate_boost_link_units` | `trigger: manual_activate, cost: rest_self, action: ap_boost(1), target: self_linked_units, duration: until_end_of_turn` |

### 持續效果 / 限制

| effectId | 標準輸出 |
|---|---|
| `blocker` | `trigger: on_block, cost: rest_self, action: block, target: self, duration: instant` |
| `attack_restriction` | `trigger: continuous, cost: none, action: no_player_attack, target: self, duration: continuous` |

### 特殊

| effectId | 標準輸出 |
|---|---|
| `pilot_designation` | `trigger: special, cost: none, action: pilot_dual, target: self, duration: continuous, parameters: {pilotName, AP, HP}` |

---

## 效果解譯範例

```yaml
st01/ST01-001:                         # 鋼彈
  level: 4
  cost: 3
  cardType: unit
  ap: 3
  hp: 4
  link: ["阿姆羅·雷"]
  effects:
    - trigger: end_of_turn
      cost: none
      action: heal(2)
      target: self
      duration: instant
      condition: null
      oncePerTurn: false
      summary: "回合結束 → 自身回復 2 HP"
    - trigger: continuous
      cost: none
      action: ap_boost(1)
      target: self_all_units
      duration: your_turn
      condition: paired
      oncePerTurn: false
      summary: "共鳴中 → 我方 Unit 在我方回合 AP+1"

st01/ST01-015:                         # 白色基地
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
      summary: "Burst → 部署此卡"
    - trigger: on_deploy
      cost: none
      action: shield_to_hand(1)
      target: self_shield
      duration: instant
      summary: "Deploy → 將 1 張盾牌加入手牌"
    - trigger: manual_activate
      cost: resource(2)
      action: deploy_token
      target: self_battle_area
      duration: instant
      oncePerTurn: true
      summary: "啟動 [Once/Turn] (2) → 依場上單位部署 T-001/T-002/T-003"

st01/ST01-012:                         # 大破
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
      summary: "主要階段 → 對 1 個橫置敵方單位造成 1 點傷害"
    - trigger: special
      cost: none
      action: pilot_dual
      target: self
      duration: continuous
      summary: "[Pilot] 可作為小林隼人（AP 0, HP 1）部署"
```
