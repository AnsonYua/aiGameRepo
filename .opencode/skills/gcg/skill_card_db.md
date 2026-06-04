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

標準化詞彙表（trigger / cost / action / target / duration 各欄位的合法值）請見 `skill_effect_vocab.md`。

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

效果解譯範例請見 `skill_effect_vocab.md`。

---

## 查詢程序

### 1. `get_card(card_id)` — 完整原始卡片資料

與之前相同：解析 card_id → 讀取 JSON 檔案 → 回傳原始卡片物件。

### 2. `interpret_effects(card_id)` — 標準化效果解譯

1. `get_card(card_id)` → 原始卡片
2. 對卡片 `effects.rules[]` 中的每條規則，套用效果解譯規則（`skill_effect_vocab.md` 中的詞彙表）— 此為內部步驟，原始 JSON 不會離開此技能
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

---

See skill_effect_vocab.md for effect interpretation details.
