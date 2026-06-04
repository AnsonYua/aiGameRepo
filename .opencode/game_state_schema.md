# Game State Schema

唯一事實來源 **runtime** `game_state.md` 的欄位定義（此文件為 schema 說明，`game_state.md` 由 orchestrator 於遊戲期間動態產生）。所有 Skill 與 Agent 讀取此結構以理解遊戲狀態。

遊戲規則見 `gcg-rulebook.md`（CR-ID 引用）。

---

## 欄位說明

```yaml
turn: <int>              # 當前回合數，先手回合開始為 1
first_player: P1|P2     # 先手玩家（P1=人類，P2=AI）
active_player: P1|P2     # 當前行動玩家
phase: <string>          # 當前階段：pre-game, start, draw, resource, main, battle, end
step: <string|null>      # 子步驟：phase=battle 時為 attack, block, action, damage, battle_end；phase=end 時為 action, cleanup；其餘 phase 為 null
current_attacker: <int|null>  # 當前攻擊的 battle_area slot 編號（phase=battle 時設定，battle_end 時清空）
priority: <active_player|null>  # 當前優先權誰屬（CR-2.9）；null = 無優先權窗口，自動階段

p1 / p2:
  base:
    card_id: <string>    # 當前 Base 卡編號（預設 EX-BASE；部署 Base 卡後變更）
    ap: <int>            # 攻擊力（EX-BASE = 0）
    hp: <int>            # 生命值（EX-BASE = 3，部署 Base 卡後依卡面）
    damage: <int>        # 已受傷害（damage >= hp 時破壞，excess 不往下傳）
    alive: <bool>        # true=存在, false=已被破壞移除
    status: active|rested|null  # Base 狀態（CR-7.5）。EX-BASE=null，部署的 Base 卡可被 rested 來支付能力費用。Start Phase 重置為 active
  shields: <int>         # 盾牌剩餘張數（開局 6，Base 底下疊放）
  hand_count: <int>      # 手牌數量（必須，display 模板需要使用 {hand_count}）
  hand_cards: [<string>] # 手牌卡片編號列表；P2 視角為 ["Unknown", ...]（隱私遮罩見 ui_templates.md §privacy_mask）
  deck_count: <int>      # 牌庫剩餘張數
  resource_deck_count: <int>  # 資源牌庫剩餘張數
  resources:
    active: <int>        # 直立資源（可支付費用）
    rested: <int>        # 橫置資源（已使用，Start Phase 重置為直立）
    ex: <int>            # EX Resources（後手起始 1，最多 5，用完移除遊戲。算入 Lv）
  battle_area:
    - slot: <int>        # 戰鬥區位置 0~5
      unit_id: <string|null>  # 單位卡編號
      pilot_id: <string|null> # 駕駛員卡編號
      ap: <int>          # 當前攻擊力
      hp: <int>          # 當前生命值
      damage: <int>      # 已受傷害
      status: <string|null># 狀態（rested 等）
      keywords: [<string>]# 關鍵字（First Strike, Blocker 等）
      link: <bool>       # 是否連結
  trash: [<string>]      # 廢棄區卡片編號列表
  removal: [<string>]    # 除外區卡片編號列表

active_effects:
  - effectId: <string>           # 效果 ID（對應 card data 的 effectId）
    source: <card_id>            # 產生此效果的卡片
    timing: <string>             # 持續類型：UNTIL_END_OF_TURN | ONCE_PER_TURN | continuous
    parameters: {<key: value>}   # 效果參數（ap/hp 修正值等）
    used_this_turn: <bool>       # once_per_turn 效果是否已用過（CR-10.4）
battle_log: [<log>]         # 戰鬥記錄（回合歸檔用）
game_over: <bool>           # 遊戲是否結束
winner: null|<string>       # 勝利者（P1/P2/null）
```

---

## Level 與費用（見 CR-3）

Level = resources.active + resources.rested + resources.ex（CR-3.1）
出牌條件：Level ≥ 卡的 Lv（CR-3.2）
支付費用：橫置 Cost 數量的資源（CR-3.3）
EX Resource 用完移除遊戲（CR-3.4）

---

## 戰鬥規則

所有戰鬥規則見 `gcg-rulebook.md`：防禦層序 CR-4，戰鬥流程 CR-5，關鍵字 CR-6，敗北 CR-9。

---

## 初始化值（遊戲開始前）

`skill_initialize` 根據 `first_player` 設定：先手 turn=1/active_player=先手，後手 EX Resource+1（CR-1.2, CR-1.4, CR-1.5, CR-1.7）。

> * 標記 `*` 者為初始化階段的值（手牌 5、shields=0、deck=45）。調度（Mulligan）完成後，`skill_pass` pre-game 會將牌庫頂 6 張設為 shields（CR-1.5 → shields=6, deck_count=39）。

| 欄位 | 先手 | 後手 |
|---|---|---|
| base.card_id | EX-BASE | EX-BASE |
| base.ap | 0 | 0 |
| base.hp | 3 | 3 |
| base.damage | 0 | 0 |
| base.alive | true | true |
| base.status | null | null |
| shields | 0* | 0* |
| hand_cards | 5 張（對手視角隱藏） | 5 張（對手視角隱藏） |
| deck_count | 45* | 45* |
| resource_deck_count | 10 | 10 |
| resources.active | 0 | 0 |
| resources.rested | 0 | 0 |
| resources.ex | 0 | 1 |
| current_attacker | null | null |
| battle_area | 6 格全 null | 6 格全 null |
| trash | [] | [] |
| removal | [] | [] |
| active_effects | [] | [] |
