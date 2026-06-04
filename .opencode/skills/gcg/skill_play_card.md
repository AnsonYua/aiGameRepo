---
name: skill_play_card
triggers: [play, deploy, pair]
phase_lock: main, battle(action), end(action)
---

# skill_play_card — 出牌

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

從手牌出牌至對應區域。處理所有卡片類型：Unit、Pilot、Command、Base、雙用途 [Pilot] 以及配對（pair）。

## 輸入

- `game_state.md` — 當前遊戲狀態
- `card_data[card_id]` — 預先提取的卡片數值 + 解譯後效果（來自 orchestrator）

## 流程

### 1. 支付費用（CR-3.2, CR-3.3）

- `Level = resources.active + resources.rested + resources.ex` 必須 ≥ `card_data[card_id].level`
- 支付費用：橫置 `card_data[card_id].cost` 個直立資源（active -= cost, rested += cost）
- 若直立資源不足，可用 EX 補足差額（CR-3.4）

### 2. 依 cardType 分派

**Unit**（`deploy <card_id>`）：
- 放入第一個空的戰區欄位（slot 0-5，第一個 unit_id=null 者）
- 設定 ap=card_data[].ap, hp=card_data[].hp, damage=0, status=null, keywords=[], link=false, turns_on_field=0
- 若 6 格全滿 → 必須 trash 現有單位騰出空間（CR-5.11）
- Token 型（level=0）不可從手牌打出（見 ui_templates.md §err_token_play）

**Pilot**（`deploy <card_id>`）：
- 放入第一個空的戰區欄位
- 設定 ap=card_data[].ap, hp=card_data[].hp, damage=0, status=null, keywords=[], link=false, turns_on_field=0

**Command**（`play <card_id>`）：
- 卡片效果立即結算（依 interpreted effects）
- 結算後卡片進 trash
- 啟動時機須符合當前階段/子步驟（CR-10.3）

**Base**（`deploy <card_id>`）：
- 舊 Base（當前 `base`）進 trash（CR-7.3）
- 最上層盾牌移至手牌（CR-7.3）。shields: -1 表示數量；實際 card_id 由 orchestrator 透過 state_diff 追蹤
- 新 Base 卡取代：card_id, hp=card_data[].hp, ap=card_data[].ap, damage=0, alive=true, status=active
- [Deploy] 觸發結算（CR-6.6）

**雙用途 [Pilot]**（選擇模式）：
- `play` → 視為 Command：結算效果，進 trash
- `deploy` → 視為 Pilot：以 [Pilot] 數值放入戰區

### 3. action step 優先權重置
- 若在 battle(action) 或 end(action) 階段，優先權返回非行動玩家（CR-2.10(c)）

### 4. 配對（`pair <pilot_card_id> <slot>`）

- 目標欄位必須有 unit_id != null 且 pilot_id = null
- Pilot 卡必須在手牌（或剛部署）
- 在欄位中設定 pilot_id
- Pilot 卡從手牌移除
- 若 pilot 可共鳴（pilot name 在 card_data[unit_id].link 中）→ 設定 link=true（CR-6.4）
- [When Paired] 觸發結算（來自 trigger=on_pair 的 interpreted effects）

## 輸出

```yaml
state_diff:
  priority: <non_active_player>     # action step 啟動後優先權返回非行動玩家（CR-2.10(c)）
  <active_player>:
    resources:
      active: -<cost>     # 支付費用後
      rested: +<cost>
      ex: -<ex_used>
    hand_cards:
      - remove: <card_id>
    battle_area:           # 部署/配對用
      - slot: <N>
        unit_id: "<card_id or unchanged>"
        pilot_id: "<pilot_id or unchanged>"
        ap: <from card_data or unchanged>
        hp: <from card_data or unchanged>
        damage: 0
        status: null
        keywords: []
        link: <true|false>
    base:                  # Base 部署用
      card_id: "<new card_id>"
      ap: <new ap>
      hp: <new hp>
      damage: 0
      alive: true
      status: active
    shields: -1            # 若為 Base 部署（最上層盾牌→手牌）
    trash:
      - add: <old card_id>
  battle_log:                          # 模板見 ui_templates.md §log_play_card
    - "<active_player> plays/deploys/pairs <card_id>"
```
