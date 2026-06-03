# Game State Schema

唯一事實來源 `game_state.md` 的欄位定義。所有 Skill 與 Agent 讀取此結構以理解遊戲狀態。

---

## 欄位說明

```yaml
turn: <int>              # 當前回合數，P1 回合開始為 1
active_player: P1|P2     # 當前行動玩家
phase: <string>          # 當前階段：pre-game, start, draw, resource, main, battle, end
step: <string|null>      # 戰鬥子步驟：attack, block, action, damage, battle_end

p1 / p2:
  base:
    name: <string>       # Base 卡名稱（預設 EX Base）
    ap: <int>            # 攻擊力
    hp: <int>            # 生命值
    damage: <int>        # 已受傷害（damage >= hp 時破壞）
  shields: <int>         # 盾牌張數（剩餘，非初始）
  hand_count: <int>      # 手牌數量（推導用，可省略）
  hand_cards: <list>     # 手牌內容；P2 視角為 ["Unknown", ...]
  deck_count: <int>      # 牌庫剩餘張數
  resource_deck_count:   # 資源牌庫剩餘張數
  resources:
    active: <int>        # 直立資源（可支付費用）
    rested: <int>        # 橫置資源（已使用，回合重置時豎直）
    ex: <int>            # EX Resources（最多 5，用於支付費用後移除遊戲）
  battle_area:
    - slot: <int>        # 戰鬥區位置 0~5
      unit: <string|null># 單位卡名稱
      pilot: <string|null># 駕駛員卡名稱
      ap: <int>          # 當前攻擊力
      hp: <int>          # 當前生命值
      damage: <int>      # 已受傷害
      status: <string|null># 狀態（rested 等）
      keywords: [<string>]# 關鍵字（First Strike 等）
      link: <bool>       # 是否連結
  trash: [<string>]      # 廢棄區卡片名稱列表
  removal: [<string>]    # 除外區卡片名稱列表

active_effects: [<effect>]  # 場上生效中的效果
battle_log: [<log>]         # 戰鬥記錄（回合歸檔用）
game_over: <bool>           # 遊戲是否結束
winner: null|<string>       # 勝利者（P1/P2/null）
```

---

## Level 推導規則

Level 不直接儲存，由 `resources.active + resources.rested + resources.ex` 計算。

---

## 初始化值（遊戲開始前）

| 欄位 | P1 | P2 |
|---|---|---|
| base | EX Base (ap=0, hp=3, damage=0) | same |
| shields | 6 (從牌庫頂) | 6 |
| hand_cards | 5 張 | 5 張（P1 視角隱藏） |
| deck_count | 44 (50-6 shields) | 44 |
| resource_deck_count | 10 | 10 |
| resources.active | 0 | 0 |
| resources.rested | 0 | 0 |
| resources.ex | 0 | 1 |
| battle_area | 6 格全 null | 6 格全 null |
| trash | [] | [] |
| removal | [] | [] |
