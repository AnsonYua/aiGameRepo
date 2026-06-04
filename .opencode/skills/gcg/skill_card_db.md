---
name: skill_card_db
type: utility
note: card data interpretation reference — not a routable skill; loaded by orchestrator for card data pre-fetch
---

# skill_card_db — 卡片資料與效果解譯

中央卡片資料庫 + 效果解譯技能。讀取原始 `card/data/*.json`，將效果解譯為標準化格式。所有 Agent（AI Player、Orchestrator、Judge）共用同一套解譯格式。

---

## 資料來源

| 來源 | 路徑 | 內容 |
|--------|------|---------|
| 卡片明細（原始） | `card/data/{set}Card.json` | 各系列的原始 JSON 效果資料 |
| 牌組清單 | `card/gcgdecks.json` | 牌組定義 + 玩家→牌組對應 |

---

## 卡片 ID 格式

正式：`{set_prefix}/{card_number}`

範例：`st01/ST01-001` → prefix=`st01`, 檔案=`card/data/st01Card.json`, 鍵值=`ST01-001`

| Prefix | 檔案 |
|--------|------|
| `st01`–`st09` | `st{nn}Card.json` |
| `gd01`–`gd03` | `gd{nn}Card.json` |

規則：`{prefix}` → `{prefix}Card.json`。card_id 中無 `/` 則搜尋所有檔案。

---

## 效果詞彙（所有 Agent 共用）

原始 `card/data/*.json` 中的每個效果規則都會被解譯為此標準結構：

```yaml
- effectId: <string>         # 卡片資料中的原始 effectId
  trigger: <trigger_type>    # 觸發時機
  cost: <cost_type>          # 需支付的費用（若有的話）
  action: <action_type>      # 做什麼
  target: <target_scope>     # 影響誰
  value: <int>               # 數值參數（若適用）
  duration: <duration_type>  # 持續時間
  condition: <string|null>   # 條件字串（例如 "paired"）
  oncePerTurn: <bool>        # 若 [Once per Turn] 則為 true
  summary: <string>          # 人類可讀的一行摘要
```

### 觸發類型

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

### 費用類型

| Raw `cost` 欄位 | 標準化 `cost` | 說明 |
|---|---|---|
| absent / none | `none` | 免費，無需費用 |
| `{ resource: N }` | `resource(N)` | 橫置 N 個直立資源 |
| `{ resource: N, oncePerTurn: true }` | `resource(N)+once` | 橫置 N 個資源，每回合一次 |
| `{ rest: self }` | `rest_self` | 橫置此卡（Base status→rested） |
| `{ cost: rest_self }`（在 params 中） | `rest_self` | Blocker：橫置自身以轉向 |

### 動作類型

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

### 目標範圍

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

### 持續時間類型

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

## card_data 輸出格式（Orchestrator 預提取）

當 orchestrator 為 AI player（或任何 Agent）預提取卡片資料時，為手牌中每張 card_id 產生以下結構：

```yaml
card_data:
  <card_id>:
    # --- 數值（永遠存在）---
    level: <int>
    cost: <int>
    cardType: unit|pilot|command|base
    ap: <int>
    hp: <int>
    link: [<string>]       # 可配對的 pilot 名稱

    # --- 解譯後效果（永遠存在）---
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

### 範例

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

---

## 查詢程序

### 1. `get_card(card_id)` — 完整原始卡片資料

與之前相同：解析 card_id → 讀取 JSON 檔案 → 回傳原始卡片物件。

### 2. `interpret_effects(card_id)` — 標準化效果解譯

1. `get_card(card_id)` → 原始卡片
2. 對卡片 `effects.rules[]` 中的每條規則，套用效果解譯規則（上述）— 此為內部步驟，原始 JSON 不會離開此技能
3. 回傳標準化效果物件陣列

### 3. `build_card_data(card_ids[])` — 預提取套件

1. 對每個 card_id，呼叫 `get_card` 然後 `interpret_effects`
2. 組裝為 `card_data` YAML（如上定義）
3. 回傳完整的 `card_data` 物件

### 4. `get_deck(playerId)` — 玩家牌組卡片列表

與之前相同：讀取 `gcgdecks.json`。

### 5. `validate_card_stats(card_id, ap, hp)` — Judge 驗證

1. `get_card(card_id)` → 檢查基礎 ap/hp 是否符合
2. 若為 unit 類型：部署後的 ap/hp 必須等於卡片基礎 ap/hp（修改分開追蹤）

---

## 備註

- EX-BASE 是內建卡片（ap=0, hp=3），不在任何資料檔案中
- T 卡需加上 set prefix（例如 `T-006` 同時存在於 `st03` 和 `gd01`）
- 卡片資料檔案為唯讀；執行期間絕不修改
- 所有 Agent 使用 `build_card_data(card_ids[])` — 僅暴露數值 + 解譯後效果
- `card/data/*.json` 中的原始 `effects.rules[]` 是編輯用資料，絕不傳遞給任何 Agent
- 新卡系列可能會引入新的 effectId — 發現時請加入其解譯規則
