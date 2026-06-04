---
name: skill_initialize
triggers: [start game]
phase_lock: pre-game
---

# skill_initialize — 遊戲初始化

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

根據 CR-1 初始化遊戲狀態，以 `first_player`（P1|P2）為準。

## 流程

1. 設定 `turn: 1`、`active_player: first_player`、`phase: pre-game`（調度發生在 pre-game，CR-2.3）
2. 後手玩家獲得 EX Resource +1（CR-1.2）
3. 從 `card/gcgdecks.json` 讀取牌組（見 `skill_card_db.md` §4 `get_deck(playerId)`），洗牌：前 5 張→手牌，剩餘 45 張→牌庫。**盾牌初始為 0，調度完成後從牌庫頂設置**（CR-1.8 → CR-1.5）
4. 初始化雙方：Base（CR-1.4）、resource_deck_count=10（CR-1.6）、battle_area=6 空欄位、trash=[]、removal=[]
5. 剩餘 45 張牌庫順序由 orchestrator 透過 state_diff 追蹤（hand_cards 與 deck_count 已足夠）
6. 回傳完整 `game_state` 作為 `state_diff` set 操作
7. 輸出後：Orchestrator 依 §5 調度流程繼續（使用 ui_templates.md §compose_mulligan）

## 輸出

```yaml
state_diff:
  turn: 1
  first_player: <P1|P2>
  active_player: <first_player>
  phase: pre-game
  step: null
  current_attacker: null
  p1:
    base: { card_id: "EX-BASE", ap: 0, hp: 3, damage: 0, alive: true, status: null }
    shields: 0
    hand_cards: [<5 card_ids, e.g. "st01/ST01-001">]
    deck_count: 45
    resource_deck_count: 10
    resources: { active: 0, rested: 0, ex: <0|1> }
    battle_area: [{slot:0,unit_id:null,pilot_id:null,ap:0,hp:0,damage:0,status:null,keywords:[],link:false}, ...]
    trash: []
    removal: []
  p2:
    # 同 p1 結構
  active_effects: []
  battle_log: ["<player> started game as first player [CR-1.1]"]  # 模板見 ui_templates.md §log_initialize
  game_over: false
  winner: null
```
